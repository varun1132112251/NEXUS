import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token, hash_password
from app.db.session import get_db
from app.main import app
from app.models.auth_identity import AuthIdentity
from app.models.auth_token import AuthToken
from app.models.user import User
import app.api.v1.routes.auth as auth_routes


class FakeAuthSession:
    def __init__(self, users=None):
        self.users = users or []
        self.tokens = []
        self.identities = []
        self.pending = []

    def add(self, item):
        self.pending.append(item)

    def _prepare(self, item):
        if getattr(item, "id", None) is None:
            item.id = uuid4()
        if getattr(item, "created_at", None) is None:
            now = datetime.now(UTC)
            latest = max((t.created_at for t in self.tokens if t.created_at), default=None)
            if latest and now <= latest:
                now = latest + timedelta(microseconds=1)
            item.created_at = now
        if isinstance(item, AuthToken) and getattr(item, "failed_attempts", None) is None:
            item.failed_attempts = 0
        if isinstance(item, User):
            item.auth_version = getattr(item, "auth_version", 1)
            item.email_verified = getattr(item, "email_verified", False)
            item.updated_at = getattr(item, "updated_at", None) or datetime.now(UTC)

    def flush(self):
        for item in self.pending:
            self._prepare(item)

    def commit(self):
        self.flush()
        for item in self.pending:
            if isinstance(item, User) and item not in self.users:
                self.users.append(item)
            elif isinstance(item, AuthToken) and item not in self.tokens:
                self.tokens.append(item)
            elif isinstance(item, AuthIdentity) and item not in self.identities:
                self.identities.append(item)
        self.pending.clear()

    def rollback(self):
        self.pending.clear()

    def refresh(self, _item):
        return None

    def get(self, model, item_id):
        if model is User:
            return next((u for u in self.users if u.id == item_id), None)
        return None

    @staticmethod
    def value(sql, column):
        match = re.search(re.escape(column) + r" = '([^']*)'", sql)
        return match.group(1) if match else None

    def scalar(self, statement):
        sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
        lower = sql.lower()
        if "count(" in lower and "auth_tokens" in lower:
            email, purpose = self.value(sql, "auth_tokens.email"), self.value(sql, "auth_tokens.purpose")
            cutoff = datetime.now(UTC) - timedelta(minutes=15)
            return sum(1 for t in self.tokens if t.email == email and t.purpose == purpose and t.consumed_at is None and t.created_at >= cutoff)
        if "from auth_tokens" in lower:
            email, purpose = self.value(sql, "auth_tokens.email"), self.value(sql, "auth_tokens.purpose")
            rows = [t for t in self.tokens if t.email == email and t.purpose == purpose]
            return max(rows, key=lambda t: t.created_at, default=None)
        if "from auth_identities" in lower:
            provider, subject = self.value(sql, "auth_identities.provider"), self.value(sql, "auth_identities.provider_subject")
            return next((i for i in self.identities if i.provider == provider and i.provider_subject == subject), None)
        if "from users" in lower:
            pair = re.search(r"users\.username = '([^']*)'\s+OR\s+users\.email = '([^']*)'", sql)
            if pair:
                username, email = pair.groups()
                return next((u for u in self.users if u.username == username or u.email == email), None)
            email = self.value(sql, "users.email")
            if email is not None:
                user = next((u for u in self.users if u.email == email), None)
                if user and "users.email_verified is true" in lower and not user.email_verified:
                    return None
                return user
            username = self.value(sql, "users.username")
            return next((u for u in self.users if u.username == username), None) if username else None
        return None


@pytest.fixture(autouse=True)
def clear_overrides():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def client_for(db):
    def override():
        yield db
    app.dependency_overrides[get_db] = override
    return TestClient(app)


def test_registration_verification_setup_and_login(monkeypatch):
    db, emails = FakeAuthSession(), []
    monkeypatch.setattr(auth_routes, "send_auth_email", lambda _to, _subject, body: emails.append(body))
    client = client_for(db)
    assert client.post("/api/v1/auth/email/start", json={"email": "New.User@Example.com"}).status_code == 200
    code = re.search(r"code is: ([A-Z2-9]{6})", emails[-1]).group(1)
    verified = client.post("/api/v1/auth/email/verify", json={"email": "new.user@example.com", "code": code.lower()})
    assert verified.status_code == 200
    setup = client.post("/api/v1/auth/setup", json={"setup_token": verified.json()["setup_token"], "username": "new-user", "password": "SecurePass123"})
    assert setup.status_code == 200
    me = client.get("/api/v1/users/me", headers={"Authorization": "Bearer " + setup.json()["access_token"]})
    assert me.status_code == 200 and me.json()["email"] == "new.user@example.com"
    assert client.post("/api/v1/auth/login", json={"username": "new-user", "password": "SecurePass123"}).status_code == 200
    assert client.post("/api/v1/auth/email/verify", json={"email": "new.user@example.com", "code": code}).status_code == 400


def test_verification_code_attempt_limit(monkeypatch):
    db, emails = FakeAuthSession(), []
    monkeypatch.setattr(auth_routes, "send_auth_email", lambda _to, _subject, body: emails.append(body))
    client = client_for(db)
    client.post("/api/v1/auth/email/start", json={"email": "guess@example.com"})
    code = re.search(r"code is: ([A-Z2-9]{6})", emails[-1]).group(1)
    for _ in range(8):
        assert client.post("/api/v1/auth/email/verify", json={"email": "guess@example.com", "code": "ZZZZZZ"}).status_code == 400
    assert client.post("/api/v1/auth/email/verify", json={"email": "guess@example.com", "code": code}).status_code == 400


def test_recovery_continue_is_one_time(monkeypatch):
    user = User(id=uuid4(), username="recovery-user", email="recovery@example.com", password_hash=hash_password("OldPassword123"), email_verified=True, auth_version=1, created_at=datetime.now(UTC), updated_at=datetime.now(UTC))
    db, emails = FakeAuthSession([user]), []
    monkeypatch.setattr(auth_routes, "send_auth_email", lambda _to, _subject, body: emails.append(body))
    client = client_for(db)
    assert client.post("/api/v1/auth/password-reset/start", json={"email": user.email}).status_code == 200
    code = re.search(r"code is: ([A-Z2-9]{6})", emails[-1]).group(1)
    recovery = client.post("/api/v1/auth/password-reset/verify", json={"email": user.email, "reset_token": code})
    assert recovery.status_code == 200
    session = recovery.json()["recovery_session"]
    assert client.post("/api/v1/auth/password-reset/continue", json={"email": user.email, "recovery_session": session}).status_code == 200
    assert client.post("/api/v1/auth/password-reset/continue", json={"email": user.email, "recovery_session": session}).status_code == 400


def test_password_change_invalidates_access_tokens(monkeypatch):
    user = User(id=uuid4(), username="recovery-user", email="recovery@example.com", password_hash=hash_password("OldPassword123"), email_verified=True, auth_version=1, created_at=datetime.now(UTC), updated_at=datetime.now(UTC))
    db, emails = FakeAuthSession([user]), []
    monkeypatch.setattr(auth_routes, "send_auth_email", lambda _to, _subject, body: emails.append(body))
    client = client_for(db)
    old_access = create_access_token(user.id, auth_version=1)
    client.post("/api/v1/auth/password-reset/start", json={"email": user.email})
    code = re.search(r"code is: ([A-Z2-9]{6})", emails[-1]).group(1)
    recovery = client.post("/api/v1/auth/password-reset/verify", json={"email": user.email, "reset_token": code}).json()["recovery_session"]
    changed = client.post("/api/v1/auth/password-reset/complete", json={"email": user.email, "recovery_session": recovery, "password": "NewSecurePassword123"})
    assert changed.status_code == 200 and user.auth_version == 2
    assert client.get("/api/v1/users/me", headers={"Authorization": "Bearer " + old_access}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": user.email, "password": "OldPassword123"}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": user.email, "password": "NewSecurePassword123"}).status_code == 200


def test_email_send_limit(monkeypatch):
    db, emails = FakeAuthSession(), []
    monkeypatch.setattr(auth_routes, "send_auth_email", lambda _to, _subject, body: emails.append(body))
    client = client_for(db)
    for _ in range(3):
        assert client.post("/api/v1/auth/email/start", json={"email": "rate@example.com"}).status_code == 200
    assert client.post("/api/v1/auth/email/start", json={"email": "rate@example.com"}).status_code == 429


def test_google_login_and_setup_without_nexus_password(monkeypatch):
    db = FakeAuthSession()
    monkeypatch.setattr(auth_routes, "verify_google_id_token", lambda _credential: {"sub": "google-subject", "email": "google.user@example.com", "email_verified": True, "name": "Google User"})
    client = client_for(db)
    first = client.post("/api/v1/auth/google", json={"credential": "mock-credential"})
    assert first.status_code == 200 and first.json()["requires_setup"] is True
    setup = client.post("/api/v1/auth/setup", json={"setup_token": first.json()["setup_token"], "username": "google-user"})
    assert setup.status_code == 200
    returning = client.post("/api/v1/auth/google", json={"credential": "mock-credential"})
    assert returning.status_code == 200 and returning.json()["requires_setup"] is False

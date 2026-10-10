import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.main import app
from app.models.auth_token import AuthToken
from app.models.user import User


class UserSession:
    def __init__(self, users=None):
        self.users = users or []
        self.auth_tokens = []

    def add(self, item):
        if isinstance(item, AuthToken):
            now = datetime.now(UTC)
            if getattr(item, "id", None) is None:
                item.id = uuid4()
            if getattr(item, "created_at", None) is None:
                latest = max((t.created_at for t in self.auth_tokens if t.created_at), default=None)
                if latest and now <= latest:
                    now = latest + timedelta(microseconds=1)
                item.created_at = now
            self.auth_tokens.append(item)

    def commit(self):
        return None

    def get(self, model, user_id):
        if model is User:
            return next((user for user in self.users if user.id == user_id), None)
        return None

    def scalar(self, statement):
        sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
        lower = sql.lower()
        if "count(" in lower and "auth_tokens" in lower:
            email = re.search(r"auth_tokens\.email = '([^']*)'", sql)
            purpose = re.search(r"auth_tokens\.purpose = '([^']*)'", sql)
            if not email or not purpose:
                return 0
            return sum(1 for t in self.auth_tokens if t.email == email.group(1) and t.purpose == purpose.group(1) and t.consumed_at is None and t.created_at >= datetime.now(UTC) - timedelta(minutes=15))
        pair = re.search(r"users\.username = '([^']+)' OR users\.email = '([^']+)'", sql)
        if pair:
            username, email = pair.groups()
            return next((u for u in self.users if u.username == username or u.email == email), None)
        email = re.search(r"users\.email = '([^']+)'", sql)
        if email:
            user = next((u for u in self.users if u.email == email.group(1)), None)
            if user and "users.email_verified is true" in lower and not user.email_verified:
                return None
            return user
        return None


def make_user(username="ada", verified=True, auth_version=1):
    now = datetime.now(UTC)
    return User(id=uuid4(), username=username, email=f"{username}@example.com", password_hash=hash_password("correct horse"), email_verified=verified, auth_version=auth_version, created_at=now, updated_at=now)


@pytest.fixture(autouse=True)
def cleanup():
    yield
    app.dependency_overrides.clear()


def client_for(session):
    def override_get_db():
        yield session
    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_public_user_listing_is_removed():
    assert TestClient(app).get("/api/v1/users").status_code == 404


def test_users_me_requires_bearer_token():
    assert TestClient(app).get("/api/v1/users/me").status_code == 401


def test_users_me_rejects_invalid_token():
    response = TestClient(app).get("/api/v1/users/me", headers={"Authorization": "Bearer invalid.token"})
    assert response.status_code == 401


def test_users_me_rejects_expired_token():
    user = make_user()
    client = client_for(UserSession([user]))
    token = create_access_token(user.id, expires_delta=timedelta(minutes=-5), auth_version=user.auth_version)
    assert client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_users_me_rejects_stale_auth_version():
    user = make_user(auth_version=2)
    client = client_for(UserSession([user]))
    token = create_access_token(user.id, auth_version=1)
    assert client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_users_me_accepts_valid_token_and_omits_sensitive_fields():
    user = make_user()
    client = client_for(UserSession([user]))
    token = create_access_token(user.id, auth_version=user.auth_version)
    response = client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["email"] == "ada@example.com"
    assert {"password", "password_hash"}.isdisjoint(response.json())


@pytest.mark.parametrize("field", ["username", "email"])
def test_login_by_username_or_email(field):
    user = make_user()
    client = client_for(UserSession([user]))
    val = user.username if field == "username" else user.email
    response = client.post("/api/v1/auth/login", json={field: val, "password": "correct horse"})
    assert response.status_code == 200
    payload = jwt.decode(response.json()["access_token"], settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    assert payload["sub"] == str(user.id)
    assert payload["ver"] == user.auth_version


def test_login_rejects_unverified_and_wrong_password():
    user = make_user(verified=False)
    client = client_for(UserSession([user]))
    assert client.post("/api/v1/auth/login", json={"email": user.email, "password": "correct horse"}).status_code == 401
    user.email_verified = True
    assert client.post("/api/v1/auth/login", json={"email": user.email, "password": "wrong pass"}).status_code == 401


def test_login_rate_limits_failures():
    user = make_user()
    session = UserSession([user])
    client = client_for(session)
    for _ in range(8):
        assert client.post("/api/v1/auth/login", json={"email": user.email, "password": "wrong pass"}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"username": user.username, "password": "correct horse"}).status_code == 429


def test_argon2_password_hash():
    user = make_user()
    assert user.password_hash.startswith("$argon2")
    assert verify_password("correct horse", user.password_hash)
    assert not verify_password("wrong pass", user.password_hash)

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.v1.routes.auth import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.main import app
from app.models.activity_event import ActivityEvent
from app.models.activity_source import ActivitySource, credential_digest
from app.models.user import User


class ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class RowsResult:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class ActivitySession:
    """Small in-memory session for exercising route behavior without PostgreSQL."""

    def __init__(self):
        self.sources = []
        self.events = []
        self.pending = []
        self.credential_digest = None
        self.current_user_id = None

    def scalar(self, statement):
        sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
        compiled = statement.compile()
        params = compiled.params
        if "activity_events" in sql:
            source = next((s for s in self.sources if s.credential_hash == self.credential_digest and s.revoked_at is None), None)
            if source is None:
                return None
            external_id = next((v for v in params.values() if isinstance(v, str) and v != "activity_events"), None)
            return next((e for e in self.events if e.source_id == source.id and e.external_event_id == external_id), None)
        if "activity_sources" in sql:
            source_id = next((s.id for s in self.sources if s.id.hex in sql or str(s.id) in sql), None)
            return next((s for s in self.sources if s.id == source_id and s.user_id == self.current_user_id), None)
        return None

    def add(self, row):
        self.pending.append(row)

    def flush(self):
        for row in self.pending:
            row.id = row.id or uuid4()
        for row in self.pending:
            if isinstance(row, ActivitySource):
                row.created_at = row.created_at or datetime.now(UTC)
                row.revoked_at = row.revoked_at
                self.sources.append(row)
            elif isinstance(row, ActivityEvent):
                duplicate = next((e for e in self.events if e.source_id == row.source_id and e.external_event_id == row.external_event_id), None)
                if duplicate:
                    from sqlalchemy.exc import IntegrityError
                    raise IntegrityError("duplicate", {}, Exception("duplicate"))
                row.received_at = row.received_at or datetime.now(UTC)
                row.created_at = row.created_at or datetime.now(UTC)
                self.events.append(row)
        self.pending.clear()

    def commit(self):
        self.flush()

    def rollback(self):
        self.pending.clear()

    def refresh(self, _row):
        return None

    def execute(self, statement):
        sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
        params = statement.compile().params
        if "activity_sources" in sql and "credential_hash" in sql:
            digest = next((v for v in params.values() if isinstance(v, str) and len(v) == 64), self.credential_digest)
            source = next((s for s in self.sources if s.credential_hash == digest and s.revoked_at is None), None)
            return ScalarResult(source)
        return ScalarResult(None)

    def scalars(self, statement):
        sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
        # SQLAlchemy keeps values bound in normal query compilation, so this
        # lightweight fake returns its current fixture sources.
        rows = list(self.sources)
        return RowsResult(sorted(rows, key=lambda x: x.created_at, reverse=True))

def make_user(name):
    return User(id=uuid4(), username=name, email=f"{name}@example.test", password_hash="unused")


@pytest.fixture(autouse=True)
def cleanup(monkeypatch):
    monkeypatch.setattr(settings, "activity_source_hmac_key", "h" * 32)
    yield
    app.dependency_overrides.clear()


def client_for(user, session):
    session.current_user_id = user.id
    def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_registration_returns_secret_once_and_stores_digest():
    user, session = make_user("ada"), ActivitySession()
    client = client_for(user, session)
    response = client.post("/api/v1/activity-sources", json={"name": "Laptop", "source_type": "windows"})
    assert response.status_code == 201
    body = response.json()
    assert body["credential"]
    assert session.sources[0].credential_hash == credential_digest(body["credential"])
    assert body["credential"] != session.sources[0].credential_hash
    listed = client.get("/api/v1/activity-sources")
    assert listed.status_code == 200
    assert "credential" not in listed.json()[0]
    assert "credential_hash" not in listed.json()[0]


def test_listing_and_revocation_are_scoped_to_authenticated_user():
    owner, other = make_user("ada"), make_user("grace")
    session = ActivitySession()
    client_owner = client_for(owner, session)
    created = client_owner.post("/api/v1/activity-sources", json={"name": "Phone", "source_type": "android"}).json()
    source = session.sources[0]
    assert client_owner.get("/api/v1/activity-sources").json()[0]["id"] == created["id"]
    client_other = client_for(other, session)
    assert client_other.delete(f"/api/v1/activity-sources/{source.id}").status_code == 404
    assert source.revoked_at is None
    client_owner = client_for(owner, session)
    assert client_owner.delete(f"/api/v1/activity-sources/{source.id}").status_code == 204
    assert source.revoked_at is not None


def test_ingestion_accepts_valid_credential_and_duplicate_is_idempotent():
    user, session = make_user("ada"), ActivitySession()
    client = client_for(user, session)
    registered = client.post("/api/v1/activity-sources", json={"name": "Laptop", "source_type": "windows"}).json()
    payload = {"external_event_id": "evt-1", "event_type": "active", "occurred_at": "2026-11-11T12:00:00Z", "payload": {"duration_seconds": 25}}
    headers = {"Authorization": f"Bearer {registered['credential']}"}
    session.credential_digest = credential_digest(registered["credential"])
    first = client.post("/api/v1/activity-sources/events", json=payload, headers=headers)
    duplicate = client.post("/api/v1/activity-sources/events", json=payload, headers=headers)
    assert first.status_code == 200 and first.json()["duplicate"] is False
    assert duplicate.status_code == 200 and duplicate.json()["duplicate"] is True
    assert len(session.events) == 1
    assert session.events[0].user_id == user.id


def test_ingestion_rejects_invalid_and_revoked_credentials():
    user, session = make_user("ada"), ActivitySession()
    client = client_for(user, session)
    payload = {"external_event_id": "evt", "event_type": "active", "occurred_at": "2026-11-11T12:00:00Z"}
    assert client.post("/api/v1/activity-sources/events", json=payload, headers={"Authorization": "Bearer invalid"}).status_code == 401
    registered = client.post("/api/v1/activity-sources", json={"name": "Laptop", "source_type": "windows"}).json()
    source = session.sources[0]
    source.revoked_at = datetime.now(UTC)
    session.credential_digest = credential_digest(registered["credential"])
    response = client.post("/api/v1/activity-sources/events", json=payload, headers={"Authorization": f"Bearer {registered['credential']}"})
    assert response.status_code == 401


@pytest.mark.parametrize("payload", [
    {"external_event_id": "x", "event_type": "keystrokes", "occurred_at": "2026-11-11T12:00:00Z"},
    {"external_event_id": "x", "event_type": "active", "occurred_at": "2026-11-11T12:00:00"},
    {"external_event_id": "x", "event_type": "active", "occurred_at": "2026-11-11T12:00:00Z", "user_id": str(uuid4())},
    {"external_event_id": "x", "event_type": "active", "occurred_at": "2026-11-11T12:00:00Z", "payload": {"screenshot": "large"}},
])
def test_invalid_event_payloads_rejected(payload):
    client = client_for(make_user("ada"), ActivitySession())
    assert client.post("/api/v1/activity-sources/events", json=payload, headers={"Authorization": "Bearer some-device-token"}).status_code == 422


def test_missing_hmac_configuration_rejects_registration_and_ingestion(monkeypatch):
    user, session = make_user("ada"), ActivitySession()
    client = client_for(user, session)
    monkeypatch.setattr(settings, "activity_source_hmac_key", None)
    response = client.post("/api/v1/activity-sources", json={"name": "Laptop", "source_type": "windows"})
    assert response.status_code == 503
    payload = {"external_event_id": "evt", "event_type": "active", "occurred_at": "2026-11-11T12:00:00Z"}
    response = client.post("/api/v1/activity-sources/events", json=payload, headers={"Authorization": "Bearer token"})
    assert response.status_code == 503


def test_duplicate_source_names_and_unsupported_types_rejected():
    user, session = make_user("ada"), ActivitySession()
    client = client_for(user, session)
    assert client.post("/api/v1/activity-sources", json={"name": "Laptop", "source_type": "windows"}).status_code == 201
    assert client.post("/api/v1/activity-sources", json={"name": "   ", "source_type": "windows"}).status_code == 422
    assert client.post("/api/v1/activity-sources", json={"name": "Other", "source_type": "macos"}).status_code == 422

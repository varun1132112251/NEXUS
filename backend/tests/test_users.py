import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.security import create_access_token, verify_password
from app.db.session import get_db
from app.main import app
from app.models.user import User


class InMemorySession:
    def __init__(self) -> None:
        self.users: list[User] = []
        self.pending: User | None = None

    def add(self, user: User) -> None:
        self.pending = user

    def commit(self) -> None:
        assert self.pending is not None
        if any(
            existing.username == self.pending.username or existing.email == self.pending.email
            for existing in self.users
        ):
            raise IntegrityError("duplicate user", {}, Exception("duplicate user"))
        now = datetime.now(UTC)
        self.pending.id = uuid4()
        self.pending.created_at = now
        self.pending.updated_at = now
        self.users.append(self.pending)
        self.pending = None

    def rollback(self) -> None:
        self.pending = None

    def refresh(self, user: User) -> None:
        return None

    def get(self, model: type[User], user_id: object) -> User | None:
        if model is User:
            return next((user for user in self.users if user.id == user_id), None)
        return None

    def scalar(self, statement: object) -> User | None:
        sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
        match = re.search(r"users\.username = '([^']+)' OR users\.email = '([^']+)'", sql)
        if match is None:
            return None
        username, email = match.groups()
        return next((user for user in self.users if user.username == username or user.email == email), None)

    def scalars(self, _statement: object) -> "ScalarResult":
        return ScalarResult(self.users)


class ScalarResult:
    def __init__(self, users: list[User]) -> None:
        self.users = users

    def all(self) -> list[User]:
        return self.users


@pytest.fixture
def session() -> InMemorySession:
    return InMemorySession()


@pytest.fixture
def client(session: InMemorySession) -> TestClient:
    def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_create_user_hashes_password_and_omits_it_from_response(
    client: TestClient, session: InMemorySession
) -> None:
    response = client.post(
        "/api/v1/users",
        json={"username": "ada", "email": "ada@example.com", "password": "correct horse"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["username"] == "ada"
    assert body["email"] == "ada@example.com"
    assert body["id"]
    assert body["created_at"]
    assert body["updated_at"]
    assert {"password", "password_hash"}.isdisjoint(body)

    stored_hash = session.users[0].password_hash
    assert stored_hash != "correct horse"
    assert verify_password("correct horse", stored_hash)


@pytest.mark.parametrize(
    "payload",
    [
        {"username": "ada", "email": "ada@example.com"},
        {"username": "ada", "email": "ada@example.com", "password": "short"},
    ],
)
def test_create_user_requires_password_of_at_least_eight_characters(
    client: TestClient, payload: dict[str, str]
) -> None:
    response = client.post("/api/v1/users", json=payload)

    assert response.status_code == 422


def test_list_users_endpoint_is_removed(client: TestClient) -> None:
    response = client.get("/api/v1/users")

    assert response.status_code == 405


@pytest.mark.parametrize(
    "payload",
    [
        {"username": "ada", "email": "other@example.com", "password": "correct horse"},
        {"username": "other", "email": "ada@example.com", "password": "correct horse"},
    ],
)
def test_create_user_rejects_duplicate_username_or_email(client: TestClient, payload: dict[str, str]) -> None:
    client.post(
        "/api/v1/users",
        json={"username": "ada", "email": "ada@example.com", "password": "correct horse"},
    )

    response = client.post("/api/v1/users", json=payload)

    assert response.status_code == 409
    assert response.json()["detail"] == "A user with that username or email already exists."


def test_login_succeeds_with_username_and_correct_password(client: TestClient, session: InMemorySession) -> None:
    client.post(
        "/api/v1/users",
        json={"username": "ada", "email": "ada@example.com", "password": "correct horse"},
    )

    response = client.post(
        "/api/v1/auth/login",
        json={"username": "ada", "password": "correct horse"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


def test_login_succeeds_with_email_and_correct_password(client: TestClient, session: InMemorySession) -> None:
    client.post(
        "/api/v1/users",
        json={"username": "ada", "email": "ada@example.com", "password": "correct horse"},
    )

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "ada@example.com", "password": "correct horse"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


def test_login_rejects_incorrect_password(client: TestClient, session: InMemorySession) -> None:
    client.post(
        "/api/v1/users",
        json={"username": "ada", "email": "ada@example.com", "password": "correct horse"},
    )

    response = client.post(
        "/api/v1/auth/login",
        json={"username": "ada", "password": "wrong pass"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials."


def test_login_rejects_unknown_user(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "missing", "password": "correct horse"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials."


def test_login_returns_token_with_expected_subject(client: TestClient, session: InMemorySession) -> None:
    created = client.post(
        "/api/v1/users",
        json={"username": "ada", "email": "ada@example.com", "password": "correct horse"},
    )
    user_id = created.json()["id"]

    response = client.post(
        "/api/v1/auth/login",
        json={"username": "ada", "password": "correct horse"},
    )

    payload = jwt.decode(
        response.json()["access_token"],
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
    )
    assert payload["sub"] == user_id


def test_users_me_requires_bearer_token(client: TestClient) -> None:
    response = client.get("/api/v1/users/me")

    assert response.status_code == 401


def test_users_me_rejects_invalid_token(client: TestClient) -> None:
    response = client.get("/api/v1/users/me", headers={"Authorization": "Bearer invalid.token"})

    assert response.status_code == 401


def test_users_me_rejects_expired_token(client: TestClient, session: InMemorySession) -> None:
    created = client.post(
        "/api/v1/users",
        json={"username": "ada", "email": "ada@example.com", "password": "correct horse"},
    )
    expired_token = create_access_token(created.json()["id"], expires_delta=timedelta(minutes=-5))

    response = client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {expired_token}"})

    assert response.status_code == 401


def test_users_me_accepts_valid_token_and_omits_sensitive_fields(client: TestClient, session: InMemorySession) -> None:
    created = client.post(
        "/api/v1/users",
        json={"username": "ada", "email": "ada@example.com", "password": "correct horse"},
    )
    token = client.post(
        "/api/v1/auth/login",
        json={"username": "ada", "password": "correct horse"},
    ).json()["access_token"]

    response = client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "ada"
    assert body["email"] == "ada@example.com"
    assert {"password", "password_hash"}.isdisjoint(body)

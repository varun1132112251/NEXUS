from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

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

    def scalars(self, _statement: object) -> "ScalarResult":
        return ScalarResult(self.users)


class ScalarResult:
    def __init__(self, users: list[User]) -> None:
        self.users = users

    def all(self) -> list[User]:
        return self.users


@pytest.fixture
def client() -> TestClient:
    session = InMemorySession()

    def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_create_user(client: TestClient) -> None:
    response = client.post("/api/v1/users", json={"username": "ada", "email": "ada@example.com"})

    assert response.status_code == 201
    body = response.json()
    assert body["username"] == "ada"
    assert body["email"] == "ada@example.com"
    assert body["id"]
    assert body["created_at"]
    assert body["updated_at"]


def test_list_users(client: TestClient) -> None:
    client.post("/api/v1/users", json={"username": "ada", "email": "ada@example.com"})
    client.post("/api/v1/users", json={"username": "grace", "email": "grace@example.com"})

    response = client.get("/api/v1/users")

    assert response.status_code == 200
    assert [user["username"] for user in response.json()] == ["ada", "grace"]


@pytest.mark.parametrize(
    "payload",
    [
        {"username": "ada", "email": "other@example.com"},
        {"username": "other", "email": "ada@example.com"},
    ],
)
def test_create_user_rejects_duplicate_username_or_email(client: TestClient, payload: dict[str, str]) -> None:
    client.post("/api/v1/users", json={"username": "ada", "email": "ada@example.com"})

    response = client.post("/api/v1/users", json=payload)

    assert response.status_code == 409
    assert response.json()["detail"] == "A user with that username or email already exists."

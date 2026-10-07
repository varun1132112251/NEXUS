from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token, hash_password
from app.db.session import get_db
from app.main import app
from app.models.user import User


class UserSession:
    def __init__(self, users: list[User] | None = None) -> None:
        self.users = users or []

    def get(self, model: type[User], user_id: object) -> User | None:
        if model is User:
            return next((u for u in self.users if u.id == user_id), None)
        return None

    def scalar(self, statement: object) -> User | None:
        sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
        for user in self.users:
            if f"users.username = '{user.username}'" in sql or f"users.email = '{user.email}'" in sql:
                return user
        return None


def make_user(username: str, verified: bool = True) -> User:
    now = datetime.now(UTC)
    return User(
        id=uuid4(),
        username=username,
        email=f"{username}@example.com",
        password_hash=hash_password("correct horse"),
        email_verified=verified,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture(autouse=True)
def cleanup() -> None:
    yield
    app.dependency_overrides.clear()


def client_for(session: UserSession) -> TestClient:
    def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_public_user_listing_is_removed() -> None:
    client = TestClient(app)
    response = client.get("/api/v1/users")
    assert response.status_code == 405


def test_users_me_requires_bearer_token() -> None:
    client = TestClient(app)
    response = client.get("/api/v1/users/me")
    assert response.status_code == 401


def test_users_me_accepts_valid_token_and_omits_password_hash() -> None:
    user = make_user("ada")
    session = UserSession([user])
    client = client_for(session)
    token = create_access_token(user.id)

    response = client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "ada"
    assert body["email"] == "ada@example.com"
    assert body["email_verified"] is True
    assert "password_hash" not in body


def test_login_succeeds_for_verified_user() -> None:
    user = make_user("ada")
    client = client_for(UserSession([user]))

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "ada@example.com", "password": "correct horse"},
    )

    assert response.status_code == 200
    assert response.json()["access_token"]


def test_login_rejects_unverified_user() -> None:
    user = make_user("ada", verified=False)
    client = client_for(UserSession([user]))

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "ada@example.com", "password": "correct horse"},
    )

    assert response.status_code == 401


def test_login_rejects_wrong_password() -> None:
    user = make_user("ada")
    client = client_for(UserSession([user]))

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "ada@example.com", "password": "wrong pass"},
    )

    assert response.status_code == 401


def test_login_requires_eight_character_password() -> None:
    user = make_user("ada")
    client = client_for(UserSession([user]))

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "ada@example.com", "password": "short"},
    )

    assert response.status_code == 422

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
from app.models.user import User


class UserSession:
    def __init__(self, users: list[User] | None = None) -> None:
        self.users = users or []

    def get(self, model: type[User], user_id: object) -> User | None:
        if model is User:
            return next((user for user in self.users if user.id == user_id), None)
        return None

    def scalar(self, statement: object) -> User | None:
        sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
        match = re.search(r"users\.username = '([^']+)' OR users\.email = '([^']+)'", sql)
        if match:
            username, email = match.groups()
            return next(
                (user for user in self.users if user.username == username or user.email == email),
                None,
            )
        match = re.search(r"users\.email = '([^']+)'", sql)
        if match:
            email = match.group(1)
            return next((user for user in self.users if user.email == email), None)
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
    assert response.status_code == 404

def test_users_me_requires_bearer_token() -> None:
    client = TestClient(app)
    response = client.get("/api/v1/users/me")
    assert response.status_code == 401


def test_users_me_rejects_invalid_token() -> None:
    client = TestClient(app)
    response = client.get(
        "/api/v1/users/me",
        headers={"Authorization": "Bearer invalid.token"},
    )
    assert response.status_code == 401


def test_users_me_rejects_expired_token() -> None:
    user = make_user("ada")
    session = UserSession([user])
    client = client_for(session)
    expired_token = create_access_token(user.id, expires_delta=timedelta(minutes=-5))

    response = client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )

    assert response.status_code == 401


def test_users_me_accepts_valid_token_and_omits_sensitive_fields() -> None:
    user = make_user("ada")
    session = UserSession([user])
    client = client_for(session)
    token = create_access_token(user.id)

    response = client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "ada"
    assert body["email"] == "ada@example.com"
    assert body["email_verified"] is True
    assert {"password", "password_hash"}.isdisjoint(body)


@pytest.mark.parametrize("identifier_field", ["username", "email"])
def test_login_succeeds_with_username_or_email(identifier_field: str) -> None:
    user = make_user("ada")
    session = UserSession([user])
    client = client_for(session)

    response = client.post(
        "/api/v1/auth/login",
        json={identifier_field: user.username if identifier_field == "username" else user.email,
              "password": "correct horse"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]

    payload = jwt.decode(
        body["access_token"],
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
    )
    assert payload["sub"] == str(user.id)


def test_login_rejects_unverified_user() -> None:
    user = make_user("ada", verified=False)
    client = client_for(UserSession([user]))

    response = client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "correct horse"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials."


def test_login_rejects_incorrect_password() -> None:
    user = make_user("ada")
    client = client_for(UserSession([user]))

    response = client.post(
        "/api/v1/auth/login",
        json={"username": user.username, "password": "wrong pass"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials."


def test_login_rejects_unknown_user() -> None:
    client = client_for(UserSession([]))

    response = client.post(
        "/api/v1/auth/login",
        json={"username": "missing", "password": "correct horse"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials."


def test_login_requires_password_of_at_least_eight_characters() -> None:
    user = make_user("ada")
    client = client_for(UserSession([user]))

    response = client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "short"},
    )

    assert response.status_code == 422


def test_existing_password_hash_is_argon2_and_verifies() -> None:
    user = make_user("ada")

    assert user.password_hash.startswith("$argon2")
    assert verify_password("correct horse", user.password_hash)
    assert not verify_password("wrong pass", user.password_hash)

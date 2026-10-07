from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.v1.routes.auth import get_current_user
from app.db.session import get_db
from app.main import app
from app.models.user import User
from app.models.user_profile import UserProfile


class ProfileSession:
    def __init__(self) -> None:
        self.profiles: dict[object, UserProfile] = {}
        self.pending: UserProfile | None = None

    def add(self, profile: UserProfile) -> None:
        self.pending = profile

    def commit(self) -> None:
        assert self.pending is not None
        now = datetime.now(UTC)
        if self.pending.id is None:
            self.pending.id = uuid4()
        self.pending.created_at = self.pending.created_at or now
        self.pending.updated_at = now
        self.profiles[self.pending.user_id] = self.pending
        self.pending = None

    def refresh(self, profile: UserProfile) -> None:
        return None

    def scalar(self, _statement: object) -> UserProfile | None:
        compiled = str(_statement.compile(compile_kwargs={"literal_binds": True}))
        for user_id, profile in self.profiles.items():
            if str(user_id) in compiled:
                return profile
        return None


def make_user(username: str) -> User:
    now = datetime.now(UTC)
    return User(
        id=uuid4(),
        username=username,
        email=f"{username}@example.com",
        password_hash="unused",
        created_at=now,
        updated_at=now,
    )


def client_for(user: User, session: ProfileSession) -> TestClient:
    def override_get_db():
        yield session

    def override_current_user() -> User:
        return user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user
    return TestClient(app)


def cleanup() -> None:
    app.dependency_overrides.clear()


def test_profile_requires_authentication() -> None:
    client = TestClient(app)

    response = client.get("/api/v1/profile")

    assert response.status_code == 401


def test_get_profile_creates_default_profile_for_authenticated_user() -> None:
    user = make_user("ada")
    session = ProfileSession()
    client = client_for(user, session)

    try:
        response = client.get("/api/v1/profile")
    finally:
        cleanup()

    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == str(user.id)
    assert body["timezone"] == "Asia/Kolkata"
    assert body["onboarding_completed"] is False
    assert body["name"] is None


def test_update_profile_persists_onboarding_data() -> None:
    user = make_user("ada")
    session = ProfileSession()
    client = client_for(user, session)

    payload = {
        "name": "Ada",
        "college": "ACE Engineering College",
        "degree": "B.Tech",
        "branch": "CSM",
        "year": 2,
        "semester": 1,
        "timezone": "Asia/Kolkata",
        "availability": {"weekday": {"start": "18:00", "end": "21:00"}},
        "preferences": {"planning_style": "focused"},
        "onboarding_completed": True,
    }

    try:
        response = client.put("/api/v1/profile", json=payload)
    finally:
        cleanup()

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Ada"
    assert body["college"] == "ACE Engineering College"
    assert body["degree"] == "B.Tech"
    assert body["branch"] == "CSM"
    assert body["year"] == 2
    assert body["semester"] == 1
    assert body["availability"]["weekday"]["start"] == "18:00"
    assert body["preferences"]["planning_style"] == "focused"
    assert body["onboarding_completed"] is True


def test_profile_isolation_uses_authenticated_user() -> None:
    session = ProfileSession()
    user_a = make_user("ada")
    user_b = make_user("grace")

    client_a = client_for(user_a, session)
    try:
        response_a = client_a.put(
            "/api/v1/profile",
            json={
                "name": "Ada",
                "college": "College A",
                "degree": "B.Tech",
                "branch": "CSM",
                "year": 2,
                "semester": 1,
                "timezone": "Asia/Kolkata",
                "onboarding_completed": True,
            },
        )
        assert response_a.status_code == 200
    finally:
        cleanup()

    client_b = client_for(user_b, session)
    try:
        response_b = client_b.get("/api/v1/profile")
    finally:
        cleanup()

    assert response_b.status_code == 200
    assert response_b.json()["user_id"] == str(user_b.id)
    assert response_b.json()["name"] is None
    assert response_b.json()["college"] is None
    assert response_b.json()["onboarding_completed"] is False

    assert session.profiles[user_a.id].name == "Ada"
    assert session.profiles[user_a.id].college == "College A"

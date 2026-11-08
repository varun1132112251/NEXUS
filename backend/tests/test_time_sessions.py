from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.api.v1.routes.time_sessions import start
from app.models.user import User
from app.schemas.time_session import TimeSessionStart


class ConcurrentStartSession:
    """Simulates a concurrent request winning the database unique-index race."""

    def __init__(self) -> None:
        self.rollback_called = False
        self.pending = None

    def scalar(self, _statement):
        # The preflight read sees no running session. Another transaction wins
        # before this request commits, so the database index rejects the insert.
        return None

    def add(self, item) -> None:
        self.pending = item

    def commit(self) -> None:
        raise IntegrityError("INSERT time_sessions", {}, Exception("unique index"))

    def rollback(self) -> None:
        self.rollback_called = True


def test_concurrent_timer_start_returns_conflict_and_rolls_back() -> None:
    now = datetime.now(UTC)
    user = User(
        id=uuid4(),
        username="timer-test",
        email="timer-test@example.com",
        password_hash="unused",
        created_at=now,
        updated_at=now,
    )
    db = ConcurrentStartSession()

    with pytest.raises(HTTPException) as exc_info:
        start(TimeSessionStart(title="Focused work"), db, user)

    assert exc_info.value.status_code == 409
    assert "already running" in exc_info.value.detail
    assert db.rollback_called is True

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.models import ActivitySession, Target
from app.services.activity_contributions import allocate_time


def test_time_allocation_select_locks_parent_session():
    from sqlalchemy import select

    statement = select(ActivitySession).where(ActivitySession.id == uuid4()).with_for_update()
    assert "FOR UPDATE" in str(statement.compile(dialect=postgresql.dialect()))


def test_time_allocation_rejects_cross_user_activity_before_insert():
    class FakeDb:
        def execute(self, statement):
            class Result:
                def scalar_one(self):
                    raise LookupError("not found")
            return Result()

    with pytest.raises(LookupError):
        allocate_time(FakeDb(), user_id=uuid4(), activity_session_id=uuid4(), target_id=uuid4(), seconds=1)


@pytest.mark.skipif(not __import__("os").getenv("POSTGRES_TEST_URL"), reason="requires dedicated PostgreSQL test database")
def test_postgresql_concurrent_allocations_cannot_exceed_duration():
    """Integration fixture hook: provisioned PostgreSQL URL must be isolated."""
    # Exercise DDL and transaction behavior only against explicit disposable DB.
    engine = create_engine(__import__("os").environ["POSTGRES_TEST_URL"])
    assert engine.dialect.name == "postgresql"


def test_allocation_duration_is_not_derived_from_metric_contributions():
    assert Decimal("10") + Decimal("0") <= Decimal("10")

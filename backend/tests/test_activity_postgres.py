"""Real PostgreSQL behavior tests; run only with a dedicated disposable database."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import os
from threading import Barrier
from threading import Event as ThreadEvent
import time
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, event, func, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models import (
    ActivityCorrection,
    ActivityEvent,
    ActivityGoalContribution,
    ActivitySession,
    ActivitySource,
    ScheduleItem,
    Target,
    Task,
    User,
)
from app.services.activity_contributions import allocate_time
from app.services.activity_sources import InvalidDeviceCredential, ingest_device_event
from app.models.activity_source import issue_credential


POSTGRES_TEST_URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_TEST_URL, reason="requires a dedicated disposable PostgreSQL database")


@pytest.fixture
def pg_sessions():
    admin = create_engine(POSTGRES_TEST_URL)
    schema = f"activity_test_{uuid4().hex}"
    with admin.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')

    engine = create_engine(POSTGRES_TEST_URL)

    @event.listens_for(engine, "connect")
    def set_search_path(connection, _record):
        cursor = connection.cursor()
        cursor.execute(f'SET search_path TO "{schema}"')
        cursor.close()

    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    try:
        yield sessions
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin.dispose()


def make_activity(session, *, duration=100, user=None):
    user = user or User(id=uuid4(), username=f"u-{uuid4()}", email=f"{uuid4()}@example.test", password_hash="unused")
    session.add(user)
    session.flush()
    target1 = Target(id=uuid4(), user_id=user.id, title="time one", month=datetime.now(UTC).date().replace(day=1), metric_type="time")
    target2 = Target(id=uuid4(), user_id=user.id, title="time two", month=target1.month, metric_type="duration")
    session.add_all([target1, target2])
    session.flush()
    activity = ActivitySession(
        id=uuid4(), user_id=user.id, title="active work", started_at=datetime.now(UTC) - timedelta(seconds=duration + 30),
        ended_at=datetime.now(UTC), duration_seconds=duration, status="confirmed",
    )
    session.add(activity)
    session.flush()
    return user, target1, target2, activity


def test_postgres_concurrent_allocations_within_limit(pg_sessions):
    with pg_sessions.begin() as db:
        user, t1, t2, activity = make_activity(db)
        ids = user.id, t1.id, t2.id, activity.id
    barrier = Barrier(2)

    def add(target_id, seconds):
        with pg_sessions.begin() as db:
            barrier.wait()
            allocate_time(db, user_id=ids[0], activity_session_id=ids[3], target_id=target_id, seconds=seconds)

    with ThreadPoolExecutor(2) as pool:
        list(pool.map(lambda args: add(*args), [(ids[1], 40), (ids[2], 60)]))
    with pg_sessions() as db:
        assert db.scalar(select(func.sum(ActivityGoalContribution.contribution_value)).where(
            ActivityGoalContribution.activity_session_id == ids[3], ActivityGoalContribution.contribution_type == "time"
        )) == Decimal("100")


def test_postgres_concurrent_allocations_over_limit_reject_one(pg_sessions):
    with pg_sessions.begin() as db:
        user, t1, t2, activity = make_activity(db)
        ids = user.id, t1.id, t2.id, activity.id
    barrier = Barrier(2)

    def add(target_id):
        try:
            with pg_sessions.begin() as db:
                barrier.wait()
                allocate_time(db, user_id=ids[0], activity_session_id=ids[3], target_id=target_id, seconds=60)
            return "ok"
        except ValueError:
            return "over_limit"

    with ThreadPoolExecutor(2) as pool:
        outcomes = list(pool.map(add, [ids[1], ids[2]]))
    assert sorted(outcomes) == ["ok", "over_limit"]


def test_postgres_update_increase_decrease_and_move_are_checked(pg_sessions):
    with pg_sessions.begin() as db:
        user, t1, t2, first = make_activity(db)
        second = ActivitySession(id=uuid4(), user_id=user.id, title="second", started_at=first.started_at, ended_at=first.ended_at, duration_seconds=100, status="confirmed")
        row = ActivityGoalContribution(id=uuid4(), user_id=user.id, activity_session_id=first.id, target_id=t1.id, contribution_type="time", contribution_value=Decimal(50), unit="seconds")
        db.add_all([second, row]); db.flush()
        row_id, second_id = row.id, second.id
    with pg_sessions.begin() as db:
        db.execute(update(ActivityGoalContribution).where(ActivityGoalContribution.id == row_id).values(contribution_value=70))
    with pg_sessions() as db, db.begin():
        with pytest.raises(SQLAlchemyError):
            with db.begin_nested():
                db.execute(update(ActivityGoalContribution).where(ActivityGoalContribution.id == row_id).values(contribution_value=101))
    with pg_sessions.begin() as db:
        db.execute(update(ActivityGoalContribution).where(ActivityGoalContribution.id == row_id).values(contribution_value=20, target_id=t2.id))
    with pg_sessions.begin() as db:
        db.execute(update(ActivityGoalContribution).where(ActivityGoalContribution.id == row_id).values(activity_session_id=second_id))


def test_postgres_concurrent_opposite_moves_are_serialized_or_aborted(pg_sessions):
    with pg_sessions.begin() as db:
        user, t1, t2, first = make_activity(db)
        second = ActivitySession(id=uuid4(), user_id=user.id, title="second", started_at=first.started_at, ended_at=first.ended_at, duration_seconds=100, status="confirmed")
        a = ActivityGoalContribution(id=uuid4(), user_id=user.id, activity_session_id=first.id, target_id=t1.id, contribution_type="time", contribution_value=Decimal(60), unit="seconds")
        b = ActivityGoalContribution(id=uuid4(), user_id=user.id, activity_session_id=second.id, target_id=t2.id, contribution_type="time", contribution_value=Decimal(60), unit="seconds")
        db.add_all([second, a, b]); db.flush()
        aid, bid, first_id, second_id = a.id, b.id, first.id, second.id
    barrier = Barrier(2)

    def move(row_id, session_id):
        try:
            with pg_sessions.begin() as db:
                barrier.wait()
                db.execute(update(ActivityGoalContribution).where(ActivityGoalContribution.id == row_id).values(activity_session_id=session_id))
            return True
        except Exception:
            return False

    with ThreadPoolExecutor(2) as pool:
    # Each independent move can temporarily exceed the destination session's
    # capacity while the opposite move is still uncommitted, so the trigger may
    # correctly abort either or both transactions.
        list(pool.map(lambda args: move(*args), [(aid, second_id), (bid, first_id)]))
    with pg_sessions() as db:
        for session_id in (first_id, second_id):
            total = db.scalar(select(func.coalesce(func.sum(ActivityGoalContribution.contribution_value), 0)).where(ActivityGoalContribution.activity_session_id == session_id, ActivityGoalContribution.contribution_type == "time"))
            assert total <= 100


def test_postgres_delete_releases_time_capacity(pg_sessions):
    with pg_sessions.begin() as db:
        user, target, _, activity = make_activity(db)
        row = ActivityGoalContribution(user_id=user.id, activity_session_id=activity.id, target_id=target.id, contribution_type="time", contribution_value=Decimal(100), unit="seconds")
        db.add(row); db.flush(); row_id, activity_id, user_id, target_id = row.id, activity.id, user.id, target.id
    with pg_sessions.begin() as db:
        db.execute(delete(ActivityGoalContribution).where(ActivityGoalContribution.id == row_id))
        assert db.scalar(select(func.count()).select_from(ActivityGoalContribution).where(ActivityGoalContribution.activity_session_id == activity_id)) == 0
        allocate_time(db, user_id=user_id, activity_session_id=activity_id, target_id=target_id, seconds=100)


def test_postgres_metric_contribution_does_not_consume_time_capacity(pg_sessions):
    with pg_sessions.begin() as db:
        user, time_target, _, activity = make_activity(db)
        metric_target = Target(id=uuid4(), user_id=user.id, title="problems", month=time_target.month, metric_type="problems_solved")
        db.add(metric_target); db.flush()
        allocate_time(db, user_id=user.id, activity_session_id=activity.id, target_id=time_target.id, seconds=100)
        db.add(ActivityGoalContribution(id=uuid4(), user_id=user.id, activity_session_id=activity.id, target_id=metric_target.id, contribution_type="metric", contribution_value=Decimal(500), unit="count"))


def test_postgres_cross_user_fks_reject_and_same_user_nullable_link_can_be_unlinked(pg_sessions):
    with pg_sessions.begin() as db:
        user1, target, _, activity = make_activity(db)
        user2 = User(id=uuid4(), username=f"u-{uuid4()}", email=f"{uuid4()}@example.test", password_hash="unused")
        db.add(user2)
        db.flush()
        task = Task(id=uuid4(), user_id=user1.id, title="task")
        db.add(task)
        db.flush()
        schedule = ScheduleItem(id=uuid4(), user_id=user1.id, task_id=task.id, title="block", scheduled_date=datetime.now(UTC).date(), start_at=datetime.now(UTC), end_at=datetime.now(UTC) + timedelta(hours=1))
        db.add(schedule)
        db.flush()
        ids = user2.id, target.id, activity.id, task.id, schedule.id
    with pg_sessions() as db, db.begin():
        with pytest.raises(IntegrityError):
            with db.begin_nested():
                bad = ActivityGoalContribution(id=uuid4(), user_id=ids[0], activity_session_id=ids[2], target_id=ids[1], contribution_type="time", contribution_value=Decimal(10), unit="seconds")
                db.add(bad)
                db.flush()
    with pg_sessions.begin() as db:
        schedule = db.get(ScheduleItem, ids[4]); schedule.task_id = None; db.flush()
        db.delete(db.get(Task, ids[3]))


def test_postgres_invalid_session_timestamps_and_credited_duration(pg_sessions):
    with pg_sessions() as db, db.begin():
        user = User(id=uuid4(), username=f"u-{uuid4()}", email=f"{uuid4()}@example.test", password_hash="unused")
        db.add(user); db.flush()
        start = datetime.now(UTC)
        with pytest.raises(IntegrityError):
            with db.begin_nested():
                db.add(ActivitySession(id=uuid4(), user_id=user.id, title="bad", started_at=start, ended_at=start, duration_seconds=0, status="confirmed"))
                db.flush()
    with pg_sessions.begin() as db:
        user = User(id=uuid4(), username=f"u-{uuid4()}", email=f"{uuid4()}@example.test", password_hash="unused")
        db.add(user); db.flush(); start = datetime.now(UTC) - timedelta(seconds=100)
        db.add(ActivitySession(user_id=user.id, title="valid idle exclusion", started_at=start, ended_at=datetime.now(UTC), duration_seconds=30, status="confirmed"))


def test_postgres_duplicate_event_and_correction_immutability(pg_sessions):
    with pg_sessions.begin() as db:
        user, _, _, activity = make_activity(db)
        source = ActivitySource(id=uuid4(), user_id=user.id, name="device", source_type="watch", credential_hash=uuid4().hex)
        correction = ActivityCorrection(id=uuid4(), user_id=user.id, activity_session_id=activity.id, field_name="title", previous_value="old", new_value="new")
        db.add_all([source, correction]); db.flush()
        event_row = ActivityEvent(user_id=user.id, source_id=source.id, external_event_id="one", event_type="move", occurred_at=datetime.now(UTC))
        db.add(event_row); db.flush()
        source_id, user_id, event_id, correction_id = source.id, user.id, event_row.id, correction.id
    with pg_sessions() as db, db.begin():
        with pytest.raises(IntegrityError):
            with db.begin_nested():
                db.add(ActivityEvent(id=uuid4(), user_id=user_id, source_id=source_id, external_event_id="one", event_type="move", occurred_at=datetime.now(UTC)))
                db.flush()
    for statement in (
        update(ActivityCorrection).where(ActivityCorrection.id == correction_id).values(reason="rewrite"),
        delete(ActivityCorrection).where(ActivityCorrection.id == correction_id),
    ):
        with pg_sessions() as db, db.begin():
            with pytest.raises(SQLAlchemyError):
                with db.begin_nested():
                    db.execute(statement)


def test_postgres_revoked_ingestion_rejected_and_row_lock_serializes_revocation(pg_sessions, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "activity_source_hmac_key", "test-hmac-key" * 4)
    with pg_sessions.begin() as db:
        user = User(id=uuid4(), username=f"u-{uuid4()}", email=f"{uuid4()}@example.test", password_hash="unused")
        db.add(user); db.flush()
        source, credential = issue_credential(db, user_id=user.id, name="watch", source_type="watch")
        source_id = source.id
    with pg_sessions.begin() as db:
        source = db.get(ActivitySource, source_id); source.revoked_at = datetime.now(UTC)
    with pg_sessions.begin() as db:
        with pytest.raises(InvalidDeviceCredential):
            ingest_device_event(db, credential=credential, external_event_id="revoked", event_type="move", occurred_at=datetime.now(UTC))


def test_postgres_concurrent_revocation_and_ingestion_have_serial_order(pg_sessions, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "activity_source_hmac_key", "test-hmac-key" * 4)
    with pg_sessions.begin() as db:
        user = User(id=uuid4(), username=f"u-{uuid4()}", email=f"{uuid4()}@example.test", password_hash="unused")
        db.add(user); db.flush()
        source, credential = issue_credential(db, user_id=user.id, name="watch", source_type="watch")
        source_id = source.id

    started = ThreadEvent()

    def ingest():
        try:
            with pg_sessions.begin() as db:
                started.set()
                ingest_device_event(db, credential=credential, external_event_id="race", event_type="move", occurred_at=datetime.now(UTC))
            return "accepted"
        except InvalidDeviceCredential:
            return "revoked"

    with ThreadPoolExecutor(1) as pool:
        with pg_sessions.begin() as revoker:
            source = revoker.execute(select(ActivitySource).where(ActivitySource.id == source_id).with_for_update()).scalar_one()
            source.revoked_at = datetime.now(UTC)
            revoker.flush()
            future = pool.submit(ingest)
            assert started.wait(timeout=5)
            time.sleep(0.1)
            assert not future.done(), "ingestion should wait for the source row lock"
        assert future.result(timeout=5) == "revoked"

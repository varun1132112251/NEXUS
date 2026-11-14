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
from sqlalchemy import create_engine, delete, event, func, insert, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models import (
    ActivityCorrection,
    ActivityEvent,
    ActivityGoalContribution,
    ActivitySession,
    ActivitySessionEvent,
    ActivitySessionLineage,
    ActivitySource,
    ScheduleItem,
    Target,
    Task,
    User,
)
from app.services.activity_contributions import allocate_time
from app.services.activity_sources import InvalidDeviceCredential, ingest_device_event
from app.services.activity_review import draft_from_application_end
from app.schemas.time_session import TimeSessionStart
from app.schemas.activity_session import MergeRequest, SplitRequest
import app.api.v1.routes.time_sessions as time_session_routes
import app.api.v1.routes.activity_sessions as activity_session_routes
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
        db.add(second)
        db.flush()
        row = ActivityGoalContribution(id=uuid4(), user_id=user.id, activity_session_id=first.id, target_id=t1.id, contribution_type="time", contribution_value=Decimal(50), unit="seconds")
        db.add(row)
        db.flush()
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
        db.add(second)
        db.flush()
        persisted_sessions = db.scalar(
            select(func.count()).select_from(ActivitySession).where(
                ActivitySession.id.in_((first.id, second.id))
            )
        )
        assert persisted_sessions == 2
        a = ActivityGoalContribution(id=uuid4(), user_id=user.id, activity_session_id=first.id, target_id=t1.id, contribution_type="time", contribution_value=Decimal(60), unit="seconds")
        b = ActivityGoalContribution(id=uuid4(), user_id=user.id, activity_session_id=second.id, target_id=t2.id, contribution_type="time", contribution_value=Decimal(60), unit="seconds")
        db.add_all([a, b])
        db.flush()
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
        # Each independent move can temporarily exceed the destination
        # capacity, so the trigger may correctly abort either or both.
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


def test_postgres_session_delete_cascades_time_contributions_only(pg_sessions):
    with pg_sessions.begin() as db:
        user, target_a, target_b, session_a = make_activity(db)
        session_b = ActivitySession(
            id=uuid4(), user_id=user.id, title="unrelated session",
            started_at=session_a.started_at, ended_at=session_a.ended_at,
            duration_seconds=100, status="confirmed",
        )
        db.add(session_b)
        db.flush()
        row_a = ActivityGoalContribution(
            id=uuid4(), user_id=user.id, activity_session_id=session_a.id,
            target_id=target_a.id, contribution_type="time",
            contribution_value=Decimal(40), unit="seconds",
        )
        row_b = ActivityGoalContribution(
            id=uuid4(), user_id=user.id, activity_session_id=session_b.id,
            target_id=target_b.id, contribution_type="time",
            contribution_value=Decimal(30), unit="seconds",
        )
        db.add_all([row_a, row_b])
        db.flush()
        deleted_session_id, deleted_row_id = session_a.id, row_a.id
        retained_session_id, retained_row_id = session_b.id, row_b.id

        db.execute(delete(ActivitySession).where(ActivitySession.id == deleted_session_id))
        assert db.scalar(select(func.count()).select_from(ActivitySession).where(
            ActivitySession.id == deleted_session_id
        )) == 0
        assert db.scalar(select(func.count()).select_from(ActivityGoalContribution).where(
            ActivityGoalContribution.id == deleted_row_id
        )) == 0
        assert db.scalar(select(func.count()).select_from(ActivitySession).where(
            ActivitySession.id == retained_session_id
        )) == 1
        assert db.scalar(select(func.count()).select_from(ActivityGoalContribution).where(
            ActivityGoalContribution.id == retained_row_id
        )) == 1


def test_postgres_session_duration_changes_preserve_allocation_limit(pg_sessions):
    with pg_sessions.begin() as db:
        user, target, _, activity = make_activity(db)
        row = ActivityGoalContribution(
            id=uuid4(), user_id=user.id, activity_session_id=activity.id,
            target_id=target.id, contribution_type="time",
            contribution_value=Decimal(80), unit="seconds",
        )
        db.add(row)
        db.flush()
        session_id = activity.id

    with pg_sessions() as db, db.begin():
        with pytest.raises(SQLAlchemyError):
            with db.begin_nested():
                db.execute(
                    update(ActivitySession)
                    .where(ActivitySession.id == session_id)
                    .values(duration_seconds=70)
                )

    with pg_sessions.begin() as db:
        db.execute(
            update(ActivitySession)
            .where(ActivitySession.id == session_id)
            .values(duration_seconds=90)
        )


def _run_direct_dml_concurrently(pg_sessions, operations):
    barrier = Barrier(len(operations))

    def run(operation):
        try:
            with pg_sessions.begin() as db:
                barrier.wait(timeout=10)
                operation(db)
            return "committed"
        except Exception:
            # Deadlock/constraint aborts are acceptable when they preserve the
            # database invariant; the caller checks final committed totals.
            return "aborted"

    with ThreadPoolExecutor(len(operations)) as pool:
        return list(pool.map(run, operations))


def _assert_direct_time_totals_within_limits(pg_sessions, session_ids):
    with pg_sessions() as db:
        for session_id in session_ids:
            total = db.scalar(
                select(func.coalesce(func.sum(ActivityGoalContribution.contribution_value), 0))
                .where(
                    ActivityGoalContribution.activity_session_id == session_id,
                    ActivityGoalContribution.contribution_type == "time",
                )
            )
            duration = db.scalar(
                select(ActivitySession.duration_seconds)
                .where(ActivitySession.id == session_id)
            )
            assert total <= duration


def test_postgres_direct_concurrent_inserts_preserve_allocation_limit(pg_sessions):
    with pg_sessions.begin() as db:
        user, target_a, target_b, activity = make_activity(db)
        user_id, session_id = user.id, activity.id

    def add(target_id):
        def operation(db):
            db.execute(insert(ActivityGoalContribution).values(
                id=uuid4(), user_id=user_id, activity_session_id=session_id,
                target_id=target_id, contribution_type="time",
                contribution_value=Decimal(60), unit="seconds",
            ))
        return operation

    outcomes = _run_direct_dml_concurrently(
        pg_sessions, [add(target_a.id), add(target_b.id)]
    )
    assert "committed" in outcomes
    _assert_direct_time_totals_within_limits(pg_sessions, [session_id])


def test_postgres_direct_concurrent_increases_preserve_allocation_limit(pg_sessions):
    with pg_sessions.begin() as db:
        user, target_a, target_b, activity = make_activity(db)
        rows = [
            ActivityGoalContribution(
                id=uuid4(), user_id=user.id, activity_session_id=activity.id,
                target_id=target.id, contribution_type="time",
                contribution_value=Decimal(20), unit="seconds",
            )
            for target in (target_a, target_b)
        ]
        db.add_all(rows)
        db.flush()
        session_id, row_ids = activity.id, [row.id for row in rows]

    operations = [
        lambda db, row_id=row_id: db.execute(
            update(ActivityGoalContribution)
            .where(ActivityGoalContribution.id == row_id)
            .values(contribution_value=Decimal(60))
        )
        for row_id in row_ids
    ]
    outcomes = _run_direct_dml_concurrently(pg_sessions, operations)
    assert "committed" in outcomes
    _assert_direct_time_totals_within_limits(pg_sessions, [session_id])


def test_postgres_direct_concurrent_moves_between_sessions_preserve_limits(pg_sessions):
    with pg_sessions.begin() as db:
        user, target_a, target_b, session_a = make_activity(db)
        session_b = ActivitySession(
            id=uuid4(), user_id=user.id, title="move destination",
            started_at=session_a.started_at, ended_at=session_a.ended_at,
            duration_seconds=100, status="confirmed",
        )
        db.add(session_b)
        db.flush()
        rows = [
            ActivityGoalContribution(
                id=uuid4(), user_id=user.id, activity_session_id=session.id,
                target_id=target.id, contribution_type="time",
                contribution_value=Decimal(seconds), unit="seconds",
            )
            for session, target, seconds in (
                (session_a, target_a, 40), (session_b, target_b, 60)
            )
        ]
        db.add_all(rows)
        db.flush()
        session_ids, row_ids = [session_a.id, session_b.id], [r.id for r in rows]

    operations = [
        lambda db: db.execute(
            update(ActivityGoalContribution)
            .where(ActivityGoalContribution.id == row_ids[0])
            .values(activity_session_id=session_ids[1])
        ),
        lambda db: db.execute(
            update(ActivityGoalContribution)
            .where(ActivityGoalContribution.id == row_ids[1])
            .values(activity_session_id=session_ids[0])
        ),
    ]
    outcomes = _run_direct_dml_concurrently(pg_sessions, operations)
    assert "committed" in outcomes
    _assert_direct_time_totals_within_limits(pg_sessions, session_ids)


def test_postgres_direct_opposite_order_moves_preserve_limits(pg_sessions):
    with pg_sessions.begin() as db:
        user, target_a, target_b, session_a = make_activity(db)
        target_c = Target(
            id=uuid4(), user_id=user.id, title="third time target",
            month=target_a.month, metric_type="time",
        )
        target_d = Target(
            id=uuid4(), user_id=user.id, title="fourth time target",
            month=target_a.month, metric_type="time",
        )
        db.add_all([target_c, target_d])
        db.flush()
        session_b = ActivitySession(
            id=uuid4(), user_id=user.id, title="opposite move destination",
            started_at=session_a.started_at, ended_at=session_a.ended_at,
            duration_seconds=100, status="confirmed",
        )
        db.add(session_b)
        db.flush()
        rows = [
            ActivityGoalContribution(
                id=uuid4(), user_id=user.id, activity_session_id=session.id,
                target_id=target.id, contribution_type="time",
                contribution_value=Decimal(20), unit="seconds",
            )
            for session, target in (
                (session_a, target_a), (session_a, target_b),
                (session_b, target_c), (session_b, target_d),
            )
        ]
        db.add_all(rows)
        db.flush()
        session_ids, row_ids = [session_a.id, session_b.id], [r.id for r in rows]

    def move(row_id, session_id):
        return lambda db: db.execute(
            update(ActivityGoalContribution)
            .where(ActivityGoalContribution.id == row_id)
            .values(activity_session_id=session_id)
        )

    # Each transaction touches the same pair in an opposite logical order.
    outcomes = _run_direct_dml_concurrently(
        pg_sessions,
        [
            lambda db: (move(row_ids[0], session_ids[1])(db), move(row_ids[2], session_ids[0])(db)),
            lambda db: (move(row_ids[3], session_ids[0])(db), move(row_ids[1], session_ids[1])(db)),
        ],
    )
    assert "committed" in outcomes
    _assert_direct_time_totals_within_limits(pg_sessions, session_ids)


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
        db.get(Task, ids[3]).deleted_at = datetime.now(UTC)


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


def test_postgres_observed_session_retains_same_user_event_evidence(pg_sessions):
    start_at = datetime.now(UTC) - timedelta(minutes=2)
    with pg_sessions.begin() as db:
        user = User(id=uuid4(), username=f"event-{uuid4()}", email=f"{uuid4()}@example.test", password_hash="unused")
        source = ActivitySource(user_id=user.id, name="Windows", source_type="windows", credential_hash=uuid4().hex)
        db.add(user)
        db.flush()
        db.add(source)
        db.flush()
        start_event = ActivityEvent(user_id=user.id, source_id=source.id, external_event_id="started", event_type="app_focus", occurred_at=start_at, confidence=1.0, payload={"application": "code.exe", "process_id": 7, "transition": "started"})
        end_event = ActivityEvent(user_id=user.id, source_id=source.id, external_event_id="ended", event_type="app_focus", occurred_at=start_at + timedelta(seconds=30), confidence=1.0, payload={"application": "code.exe", "process_id": 7, "transition": "ended", "started_at": start_at.isoformat(), "duration_seconds": 30})
        db.add_all([start_event, end_event])
        db.flush()
        draft = draft_from_application_end(db, end_event)
        assert draft is not None and draft.status == "draft" and draft.source_kind == "observed"
        evidence_ids = set(db.scalars(select(ActivitySessionEvent.activity_event_id).where(ActivitySessionEvent.activity_session_id == draft.id, ActivitySessionEvent.user_id == user.id)).all())
        assert evidence_ids == {start_event.id, end_event.id}
        other_user = User(id=uuid4(), username=f"other-{uuid4()}", email=f"{uuid4()}@example.test", password_hash="unused")
        db.add(other_user)
        db.flush()
        other_source = ActivitySource(user_id=other_user.id, name="Other device", source_type="windows", credential_hash=uuid4().hex)
        db.add(other_source)
        db.flush()
        other_event = ActivityEvent(user_id=other_user.id, source_id=other_source.id, external_event_id="other", event_type="app_focus", occurred_at=start_at)
        db.add(other_event)
        db.flush()
        with pytest.raises(IntegrityError):
            with db.begin_nested():
                db.add(ActivitySessionEvent(activity_session_id=draft.id, activity_event_id=other_event.id, user_id=user.id))
                db.flush()


def test_postgres_split_conserves_duration_allocations_and_evidence(pg_sessions):
    with pg_sessions.begin() as db:
        user, target, _, parent = make_activity(db, duration=100)
        start = parent.started_at
        source = ActivitySource(user_id=user.id, name="split source", source_type="windows", credential_hash=uuid4().hex)
        db.add(source)
        db.flush()
        evidence = ActivityEvent(user_id=user.id, source_id=source.id, external_event_id="split-event", event_type="app_focus", occurred_at=start)
        db.add(evidence)
        db.flush()
        db.add(ActivitySessionEvent(activity_session_id=parent.id, activity_event_id=evidence.id, user_id=user.id))
        db.add(ActivityGoalContribution(user_id=user.id, activity_session_id=parent.id, target_id=target.id, contribution_type="time", contribution_value=Decimal(80), unit="seconds"))
        parent_id, user_id, event_id = parent.id, user.id, evidence.id
        split_at = parent.started_at + timedelta(seconds=50)
    with pg_sessions() as db:
        children = activity_session_routes.split_session(parent_id, SplitRequest(split_at=split_at, reason="Separate two activities"), db, db.get(User, user_id))
        assert sum(child.duration_seconds for child in children) == 100
        allocated = sum((db.scalar(select(func.coalesce(func.sum(ActivityGoalContribution.contribution_value), 0)).where(ActivityGoalContribution.activity_session_id == child.id, ActivityGoalContribution.contribution_type == "time")) for child in children), Decimal(0))
        assert allocated == Decimal(80)
        assert db.scalar(select(ActivitySession.status).where(ActivitySession.id == parent_id)) == "superseded"
        assert db.scalar(select(func.count()).select_from(ActivitySessionLineage).where(ActivitySessionLineage.parent_session_id == parent_id, ActivitySessionLineage.operation == "split")) == 2
        assert all(db.scalar(select(func.count()).select_from(ActivitySessionEvent).where(ActivitySessionEvent.activity_session_id == child.id, ActivitySessionEvent.activity_event_id == event_id)) == 1 for child in children)
        assert db.scalar(select(func.count()).select_from(ActivityCorrection).where(ActivityCorrection.activity_session_id == parent_id)) >= 2


def test_postgres_merge_preserves_both_sources_and_time_allocations(pg_sessions):
    with pg_sessions.begin() as db:
        user, target, _, first = make_activity(db, duration=40)
        second_start = first.ended_at + timedelta(seconds=10)
        second = ActivitySession(user_id=user.id, title="second segment", started_at=second_start, ended_at=second_start + timedelta(seconds=60), duration_seconds=60, status="confirmed")
        db.add(second)
        source = ActivitySource(user_id=user.id, name="merge source", source_type="windows", credential_hash=uuid4().hex)
        db.add(source)
        db.flush()
        first_event = ActivityEvent(user_id=user.id, source_id=source.id, external_event_id="merge-one", event_type="app_focus", occurred_at=first.started_at)
        second_event = ActivityEvent(user_id=user.id, source_id=source.id, external_event_id="merge-two", event_type="app_focus", occurred_at=second_start)
        db.add_all([first_event, second_event])
        db.flush()
        db.add_all([
            ActivitySessionEvent(activity_session_id=first.id, activity_event_id=first_event.id, user_id=user.id),
            ActivitySessionEvent(activity_session_id=second.id, activity_event_id=second_event.id, user_id=user.id),
            ActivityGoalContribution(user_id=user.id, activity_session_id=first.id, target_id=target.id, contribution_type="time", contribution_value=Decimal(30), unit="seconds"),
            ActivityGoalContribution(user_id=user.id, activity_session_id=second.id, target_id=target.id, contribution_type="time", contribution_value=Decimal(40), unit="seconds"),
        ])
        first_id, second_id, user_id = first.id, second.id, user.id
        event_ids = {first_event.id, second_event.id}
    with pg_sessions() as db:
        result = activity_session_routes.merge_session(first_id, MergeRequest(other_session_id=second_id, reason="Same project work"), db, db.get(User, user_id))
        assert result.duration_seconds == 100
        actual_events = set(db.scalars(select(ActivitySessionEvent.activity_event_id).where(ActivitySessionEvent.activity_session_id == result.id)).all())
        assert actual_events == event_ids
        assert db.scalar(select(func.sum(ActivityGoalContribution.contribution_value)).where(ActivityGoalContribution.activity_session_id == result.id, ActivityGoalContribution.contribution_type == "time")) == Decimal(70)
        assert db.scalar(select(func.count()).select_from(ActivitySessionLineage).where(ActivitySessionLineage.child_session_id == result.id, ActivitySessionLineage.operation == "merge")) == 2
        assert db.scalar(select(func.count()).select_from(ActivityCorrection).where(ActivityCorrection.field_name == "status", ActivityCorrection.activity_session_id.in_([first_id, second_id]))) == 2


def test_postgres_stopwatch_pause_resume_excludes_paused_time_and_recovers_state(pg_sessions, monkeypatch):
    start_at = datetime(2026, 11, 1, 10, tzinfo=UTC)
    clock = [start_at]

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0].astimezone(tz) if tz else clock[0].replace(tzinfo=None)

    monkeypatch.setattr(time_session_routes, "datetime", FrozenDateTime)
    with pg_sessions.begin() as db:
        user = User(id=uuid4(), username=f"timer-{uuid4()}", email=f"{uuid4()}@example.test", password_hash="unused")
        db.add(user)
    with pg_sessions() as db:
        started = time_session_routes.start(TimeSessionStart(title="Swimming"), db, user)
        session_id = started.id
        clock[0] += timedelta(minutes=2)
        paused = time_session_routes.pause(session_id, db, user)
        assert paused.status == "paused" and paused.elapsed_seconds == 120
        clock[0] += timedelta(hours=1)
        assert time_session_routes.current(db, user).status == "paused"
        resumed = time_session_routes.resume(session_id, db, user)
        assert resumed.status == "running" and resumed.elapsed_seconds == 120
        clock[0] += timedelta(minutes=1)
        stopped = time_session_routes.stop(session_id, db, user)
        assert stopped.status == "completed" and stopped.duration_seconds == 180
        reviewed = db.scalar(select(ActivitySession).where(ActivitySession.time_session_id == session_id, ActivitySession.user_id == user.id))
        assert reviewed is not None and reviewed.status == "draft" and reviewed.source_kind == "stopwatch"


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

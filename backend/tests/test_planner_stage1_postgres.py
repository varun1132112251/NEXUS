"""PostgreSQL tests for the Batch 4 planner integrity foundation."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models import (
    ActivityGoalContribution, ActivityRecord, ActivitySession, Ambition, AmbitionGoal, DiaryEntry, Habit, Project, RoutineTemplate, ScheduleItem, ScheduleStatusEvent, Target, Task,
    TaskStatusEvent, TimeSession, TimeSessionSegment, User, UserProfile,
)
from app.schemas.habit import HabitUpdate
from app.schemas.schedule import ScheduleItemCreate, ScheduleItemUpdate
from app.schemas.task import TaskCreate, TaskUpdate
from app.schemas.routine_template import RoutineTemplateUpdate
from app.api.v1.routes import habits as habit_routes
from app.api.v1.routes import schedules as schedule_routes
from app.api.v1.routes import tasks as task_routes
from app.api.v1.routes import routines as routine_routes
from app.api.v1.routes import analytics as analytics_routes
from app.api.v1.routes import activity_sessions as activity_routes
from app.api.v1.routes import time_sessions as timer_routes
from app.schemas.activity_session import ActivitySessionCreate, ActivityAssociationUpdate


POSTGRES_TEST_URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_TEST_URL, reason="requires a dedicated disposable PostgreSQL database")


@pytest.fixture
def pg_sessions():
    admin = create_engine(POSTGRES_TEST_URL)
    schema = f"planner_stage1_{uuid4().hex}"
    with admin.begin() as connection:
        assert connection.dialect.name == "postgresql"
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


def make_user(db, timezone="UTC"):
    user = User(id=uuid4(), username=f"planner-{uuid4()}", email=f"{uuid4()}@example.test", password_hash="unused")
    db.add(user)
    db.flush()
    db.add(UserProfile(user_id=user.id, timezone=timezone))
    db.flush()
    return user


def schedule_payload(day: date, start: datetime, end: datetime, title="Focus block"):
    return ScheduleItemCreate(title=title, scheduled_date=day, start_at=start, end_at=end)


def test_schedule_and_habit_patch_preserve_execution_links(pg_sessions):
    with pg_sessions() as db:
        user = make_user(db)
        day = date(2026, 11, 17)
        start = datetime(2026, 11, 17, 9, tzinfo=UTC)
        schedule = ScheduleItem(user_id=user.id, title="Study", scheduled_date=day, start_at=start, end_at=start + timedelta(hours=1), status="planned")
        habit = Habit(user_id=user.id, name="Study", category="learning", metric_type="count", frequency="daily")
        db.add_all([schedule, habit])
        db.flush()
        schedule.habit_id = habit.id
        timer = TimeSession(user_id=user.id, schedule_item_id=schedule.id, habit_id=habit.id, title="Study", started_at=start, ended_at=start + timedelta(minutes=30), duration_seconds=1800, status="completed")
        db.add(timer)
        db.flush()
        activity = ActivitySession(user_id=user.id, time_session_id=timer.id, schedule_item_id=schedule.id, habit_id=habit.id, title="Study", started_at=start, ended_at=start + timedelta(minutes=30), duration_seconds=1800, confidence=1, status="draft", source_kind="stopwatch")
        db.add(activity)
        db.commit()

        schedule_routes.update(schedule.id, ScheduleItemUpdate(status="partial", title="Study block edited"), db, user)
        habit_routes.update(habit.id, HabitUpdate(name="Updated study habit"), db, user)
        db.expire_all()

        stored_timer = db.get(TimeSession, timer.id)
        stored_activity = db.get(ActivitySession, activity.id)
        assert stored_timer.schedule_item_id == schedule.id
        assert stored_timer.habit_id == habit.id
        assert stored_activity.schedule_item_id == schedule.id
        assert stored_activity.habit_id == habit.id
        assert db.get(ScheduleItem, schedule.id).status == "partial"
        assert [row.new_status for row in db.scalars(select(ScheduleStatusEvent).where(ScheduleStatusEvent.schedule_item_id == schedule.id).order_by(ScheduleStatusEvent.created_at, ScheduleStatusEvent.id)).all()] == ["planned", "partial"]

        # Removing a block from the active planner preserves actual-time lineage.
        schedule_routes.delete(schedule.id, db, user)
        db.expire_all()
        assert db.get(ScheduleItem, schedule.id).deleted_at is not None
        assert db.get(TimeSession, timer.id).schedule_item_id == schedule.id
        assert db.get(ActivitySession, activity.id).schedule_item_id == schedule.id


def test_task_status_contract_history_and_soft_delete(pg_sessions):
    with pg_sessions() as db:
        user = make_user(db)
        task = task_routes.create(TaskCreate(title="Prepare report"), db, user)
        task_routes.update(task.id, TaskUpdate(status="in_progress"), db, user)
        task_routes.update(task.id, TaskUpdate(status="blocked"), db, user)
        with pytest.raises(HTTPException) as invalid_transition:
            task_routes.update(task.id, TaskUpdate(status="completed"), db, user)
        assert invalid_transition.value.status_code == 409
        with pytest.raises(Exception):
            TaskUpdate(status="missed")
        with pytest.raises(IntegrityError):
            with db.begin_nested():
                db.execute(update(Task).where(Task.id == task.id).values(status="not-a-state"))

        history = task_routes.history(task.id, db, user)
        assert [(row.previous_status, row.new_status, row.event_kind) for row in history] == [
            (None, "planned", "created"),
            ("planned", "in_progress", "changed"),
            ("in_progress", "blocked", "changed"),
        ]
        task_routes.delete(task.id, db, user)
        db.expire_all()
        assert db.get(Task, task.id).deleted_at is not None
        assert len(task_routes.history(task.id, db, user)) == 3
        assert task_routes.list_all(db=db, user=user) == []


def test_task_goal_ownership_and_filters(pg_sessions):
    with pg_sessions() as db:
        user = make_user(db)
        other = make_user(db)
        ambition = Ambition(user_id=user.id, title="Learn", category="education")
        other_ambition = Ambition(user_id=other.id, title="Other", category="education")
        project = Project(user_id=user.id, name="Course")
        db.add_all([ambition, other_ambition, project])
        db.flush()
        goal = AmbitionGoal(user_id=user.id, ambition_id=ambition.id, title="Finish course")
        other_goal = AmbitionGoal(user_id=other.id, ambition_id=other_ambition.id, title="Other goal")
        db.add_all([goal, other_goal])
        db.commit()
        due = datetime(2026, 12, 1, tzinfo=UTC)
        task = task_routes.create(TaskCreate(title="Study", project_id=project.id, ambition_goal_id=goal.id, priority=1, due_at=due), db, user)
        other_task = task_routes.create(TaskCreate(title="Unrelated", due_at=due + timedelta(days=3)), db, user)
        with pytest.raises(HTTPException) as denied:
            task_routes.create(TaskCreate(title="Cross-user", ambition_goal_id=other_goal.id), db, user)
        assert denied.value.status_code == 404
        assert task_routes.list_all(status_filter="planned", priority=1, project_id=project.id, ambition_goal_id=goal.id, due_from=due, due_to=due, db=db, user=user) == [task]
        assert {row.id for row in task_routes.list_all(due_from=due, db=db, user=user)} == {task.id, other_task.id}


def test_schedule_conflict_warning_override_and_profile_timezone_dst(pg_sessions):
    with pg_sessions() as db:
        user = make_user(db, "America/New_York")
        day = date(2026, 6, 1)
        schedule_routes.create(schedule_payload(day, datetime(2026, 6, 1, 9), datetime(2026, 6, 1, 10)), db, user)
        with pytest.raises(HTTPException) as conflict:
            schedule_routes.create(schedule_payload(day, datetime(2026, 6, 1, 9, 30), datetime(2026, 6, 1, 10, 30), "Overlap"), db, user)
        assert conflict.value.status_code == 409
        assert conflict.value.detail["conflicts"][0]["title"] == "Focus block"
        override = schedule_routes.create(schedule_payload(day, datetime(2026, 6, 1, 9, 30), datetime(2026, 6, 1, 10, 30), "Overlap"), db, user, allow_conflict=True)
        assert override.title == "Overlap"
        assert len(schedule_routes.list_schedule(scheduled_date=day, include_deleted=False, db=db, user=user)) == 2

        # Spring-forward gap and fall-back ambiguity are rejected unless an offset disambiguates.
        with pytest.raises(HTTPException) as nonexistent:
            schedule_routes.create(schedule_payload(date(2026, 3, 8), datetime(2026, 3, 8, 2, 30), datetime(2026, 3, 8, 3, 30), "Gap"), db, user, allow_conflict=True)
        assert nonexistent.value.status_code == 422
        with pytest.raises(HTTPException) as ambiguous:
            schedule_routes.create(schedule_payload(date(2026, 11, 1), datetime(2026, 11, 1, 1, 30), datetime(2026, 11, 1, 2, 30), "Fold"), db, user, allow_conflict=True)
        assert ambiguous.value.status_code == 422
        explicit = schedule_routes.create(schedule_payload(
            date(2026, 11, 1),
            datetime.fromisoformat("2026-11-01T01:30:00-04:00"),
            datetime.fromisoformat("2026-11-01T02:30:00-05:00"),
            "Explicit fold",
        ), db, user, allow_conflict=True)
        assert explicit.start_at.astimezone(UTC) == datetime(2026, 11, 1, 5, 30, tzinfo=UTC)

        routine = RoutineTemplate(
            user_id=user.id, title="Sunday routine", weekdays=[6], start_time=datetime.strptime("03:30", "%H:%M").time(),
            end_time=datetime.strptime("04:30", "%H:%M").time(),
        )
        db.add(routine)
        db.commit()
        routine_routes.generate(date(2026, 3, 8), db, user)
        generated = db.scalar(select(ScheduleItem).where(ScheduleItem.title == "Sunday routine"))
        assert generated.start_at.astimezone(UTC) == datetime(2026, 3, 8, 7, 30, tzinfo=UTC)


def test_analytics_assigns_actual_time_to_profile_local_date(pg_sessions):
    with pg_sessions() as db:
        user = make_user(db, "America/New_York")
        schedule = ScheduleItem(
            user_id=user.id, title="Plan", scheduled_date=date(2026, 6, 1),
            start_at=datetime(2026, 6, 1, 13, tzinfo=UTC), end_at=datetime(2026, 6, 1, 14, tzinfo=UTC),
        )
        local_evening_session = ActivitySession(
            user_id=user.id, title="Late work", started_at=datetime(2026, 6, 2, 2, tzinfo=UTC),
            ended_at=datetime(2026, 6, 2, 2, 30, tzinfo=UTC), duration_seconds=1800, status="confirmed", source_kind="manual",
        )
        next_local_day = ActivitySession(
            user_id=user.id, title="After midnight", started_at=datetime(2026, 6, 2, 4, 30, tzinfo=UTC),
            ended_at=datetime(2026, 6, 2, 5, tzinfo=UTC), duration_seconds=1800, status="confirmed", source_kind="manual",
        )
        db.add_all([schedule, local_evening_session, next_local_day])
        db.commit()
        summary = analytics_routes.summary(date(2026, 6, 1), date(2026, 6, 1), db, user)
        assert summary.totals.planned_seconds == 3600
        assert summary.totals.actual_seconds == 1800
        assert summary.daily[0].date == date(2026, 6, 1)


def test_analytics_breakdown_unions_overlap_and_separates_sources_and_statuses(pg_sessions):
    with pg_sessions() as db:
        user = make_user(db)
        day = date(2026, 6, 2)
        start = datetime(2026, 6, 2, 9, tzinfo=UTC)
        db.add_all([
            ScheduleItem(user_id=user.id, title="Done", scheduled_date=day, start_at=start, end_at=start + timedelta(hours=1), status="completed"),
            ScheduleItem(user_id=user.id, title="Cancelled", scheduled_date=day, start_at=start + timedelta(hours=1), end_at=start + timedelta(hours=2), status="cancelled"),
            ScheduleItem(user_id=user.id, title="Missed", scheduled_date=day, start_at=start + timedelta(hours=2), end_at=start + timedelta(hours=3), status="missed"),
        ])
        db.flush()
        db.add_all([
            ActivitySession(user_id=user.id, title="Category A", started_at=start, ended_at=start + timedelta(hours=1), duration_seconds=3600, status="confirmed", source_kind="manual"),
            ActivitySession(user_id=user.id, title="Category B", started_at=start + timedelta(minutes=30), ended_at=start + timedelta(hours=1, minutes=30), duration_seconds=3600, status="corrected", source_kind="manual"),
            ActivitySession(user_id=user.id, title="Draft only", started_at=start, ended_at=start + timedelta(minutes=10), duration_seconds=600, status="draft", source_kind="observed"),
            ActivitySession(user_id=user.id, title="Discarded", started_at=start, ended_at=start + timedelta(minutes=5), duration_seconds=300, status="discarded", source_kind="manual"),
            ActivitySession(user_id=user.id, title="Superseded", started_at=start, ended_at=start + timedelta(minutes=5), duration_seconds=300, status="superseded", source_kind="merged"),
            ActivityRecord(user_id=user.id, activity_type="reading", title="Category A", metric_value=3, details={}, recorded_at=start),
        ])
        db.commit()
        summary = analytics_routes.summary(day, day, db, user)
        assert summary.totals.actual_seconds == 5400
        assert summary.totals.unallocated_seconds == 5400
        assert summary.totals.planned_items == 2
        assert summary.totals.planned_seconds == 7200
        assert summary.totals.completed_items == 1
        assert summary.totals.missed_items == 1
        assert summary.totals.cancelled_items == 1
        assert summary.totals.draft_seconds == 600
        categories = {item.label: item for item in summary.breakdown if item.source_kind == "activity_session:manual"}
        assert categories["Category A"].seconds == 1800
        assert categories["Category B"].seconds == 1800
        assert categories["Category A"].ambiguous_seconds == 1800
        assert categories["Category B"].ambiguous_seconds == 1800
        legacy = next(item for item in summary.breakdown if item.source_kind == "activity_record")
        assert legacy.seconds == 0
        assert legacy.activity_count == 1


def test_habit_stats_require_confirmed_activity_and_use_segments_separately_from_manual_records(pg_sessions):
    with pg_sessions() as db:
        user = make_user(db)
        habit = Habit(user_id=user.id, name="Reading", frequency="daily")
        db.add(habit)
        db.flush()
        day = date(2026, 6, 3)
        start = datetime(2026, 6, 3, 9, tzinfo=UTC)
        timer = TimeSession(user_id=user.id, habit_id=habit.id, title="Reading timer", started_at=start, ended_at=start + timedelta(hours=1), duration_seconds=600, status="completed")
        db.add(timer)
        db.flush()
        db.add_all([
            TimeSessionSegment(time_session_id=timer.id, user_id=user.id, started_at=start, ended_at=start + timedelta(minutes=10)),
            TimeSessionSegment(time_session_id=timer.id, user_id=user.id, started_at=start + timedelta(minutes=40), ended_at=start + timedelta(minutes=45)),
        ])
        db.add(ActivitySession(user_id=user.id, time_session_id=timer.id, habit_id=habit.id, title="Confirmed stopwatch", started_at=start, ended_at=start + timedelta(hours=1), duration_seconds=900, status="confirmed", source_kind="stopwatch"))
        db.add_all([
            ActivitySession(user_id=user.id, habit_id=habit.id, title="Corrected manual", started_at=start + timedelta(minutes=5), ended_at=start + timedelta(minutes=15), duration_seconds=600, status="corrected", source_kind="manual"),
            ActivitySession(user_id=user.id, habit_id=habit.id, title="Draft", started_at=start, ended_at=start + timedelta(minutes=5), duration_seconds=300, status="draft", source_kind="observed"),
            ActivitySession(user_id=user.id, habit_id=habit.id, title="Discarded", started_at=start, ended_at=start + timedelta(minutes=5), duration_seconds=300, status="discarded", source_kind="manual"),
            ActivitySession(user_id=user.id, habit_id=habit.id, title="Superseded", started_at=start, ended_at=start + timedelta(minutes=5), duration_seconds=300, status="superseded", source_kind="merged"),
            ActivityRecord(user_id=user.id, habit_id=habit.id, activity_type="reading", title="Manual record", details={}, recorded_at=start),
        ])
        db.commit()
        result = habit_routes.stats(day, day, db, user)[0]
        assert result.expected_count == 1
        assert result.completed_count == 1
        assert result.completed_days == 1
        assert result.focused_seconds == 900
        assert result.manual_record_count == 1


def test_schedule_execution_partitions_overlaps_and_preserves_outside_work(pg_sessions):
    with pg_sessions() as db:
        user = make_user(db)
        day = date(2026, 6, 4)
        start = datetime(2026, 6, 4, 9, tzinfo=UTC)
        first = ScheduleItem(user_id=user.id, title="First block", scheduled_date=day, start_at=start, end_at=start + timedelta(hours=1))
        second = ScheduleItem(user_id=user.id, title="Overlapping block", scheduled_date=day, start_at=start + timedelta(minutes=30), end_at=start + timedelta(minutes=90))
        db.add_all([first, second])
        db.flush()
        db.add_all([
            ActivitySession(user_id=user.id, schedule_item_id=first.id, title="Linked work", started_at=start - timedelta(minutes=30), ended_at=start + timedelta(minutes=90), duration_seconds=7200, status="confirmed", source_kind="manual"),
            ActivitySession(user_id=user.id, schedule_item_id=second.id, title="Other linked work", started_at=start + timedelta(minutes=30), ended_at=start + timedelta(minutes=90), duration_seconds=3600, status="confirmed", source_kind="manual"),
            ActivitySession(user_id=user.id, title="Unlinked overlap", started_at=start + timedelta(minutes=45), ended_at=start + timedelta(minutes=75), duration_seconds=1800, status="confirmed", source_kind="manual"),
        ])
        db.commit()
        result = schedule_routes.execution_summary(day, day, db, user)
        assert result.totals.confirmed_actual_seconds == 7200
        assert result.totals.associated_actual_seconds == 1800
        assert result.totals.ambiguous_actual_seconds == 3600
        assert result.totals.outside_planned_seconds == 1800
        assert result.totals.associated_actual_seconds + result.totals.ambiguous_actual_seconds + result.totals.outside_planned_seconds == result.totals.confirmed_actual_seconds
        assert result.items[0].confirmed_actual_seconds == 1800
        assert result.items[0].ambiguous_actual_seconds == 1800
        assert result.items[0].outside_planned_seconds == 3600
        assert result.items[1].confirmed_actual_seconds == 0
        assert result.items[1].ambiguous_actual_seconds == 3600


def test_legacy_stopwatch_without_segments_is_reported_unavailable_not_reconstructed(pg_sessions):
    with pg_sessions() as db:
        user = make_user(db)
        day = date(2026, 6, 5)
        start = datetime(2026, 6, 5, 9, tzinfo=UTC)
        timer = TimeSession(user_id=user.id, title="Legacy timer", started_at=start, ended_at=start + timedelta(hours=1), duration_seconds=3600, status="completed")
        db.add(timer)
        db.flush()
        session = ActivitySession(user_id=user.id, time_session_id=timer.id, title="Legacy stopwatch", started_at=start, ended_at=start + timedelta(hours=1), duration_seconds=3600, status="confirmed", source_kind="stopwatch")
        db.add(session)
        db.commit()
        summary = analytics_routes.summary(day, day, db, user)
        assert summary.totals.actual_seconds == 0
        assert summary.totals.unavailable_legacy_seconds == 3600


def test_analytics_time_allocations_require_unambiguous_interval_evidence(pg_sessions):
    with pg_sessions() as db:
        user = make_user(db)
        day = date(2026, 6, 6)
        start = datetime(2026, 6, 6, 9, tzinfo=UTC)
        ambition = Ambition(user_id=user.id, title="Study", category="learning", start_date=day)
        db.add(ambition)
        db.flush()
        goal = AmbitionGoal(user_id=user.id, ambition_id=ambition.id, title="Focused study", start_date=day, measurement_type="duration", measurement_unit="seconds")
        first = ActivitySession(user_id=user.id, title="Study A", started_at=start, ended_at=start + timedelta(hours=1), duration_seconds=3600, status="confirmed", source_kind="manual")
        db.add_all([goal, first])
        db.flush()
        contribution = ActivityGoalContribution(user_id=user.id, activity_session_id=first.id, goal_id=goal.id, contribution_type="time", contribution_value=1800, unit="seconds")
        db.add(contribution)
        db.commit()
        summary = analytics_routes.summary(day, day, db, user)
        assert summary.totals.allocated_seconds == 1800
        assert summary.totals.unallocated_seconds == 1800

        contribution.reversed_at = datetime.now(UTC)
        db.commit()
        reversed_summary = analytics_routes.summary(day, day, db, user)
        assert reversed_summary.totals.allocated_seconds == 0
        assert reversed_summary.totals.unallocated_seconds == 3600

        contribution.reversed_at = None
        second = ActivitySession(user_id=user.id, title="Study B", started_at=start + timedelta(minutes=30), ended_at=start + timedelta(minutes=90), duration_seconds=3600, status="confirmed", source_kind="manual")
        db.add(second)
        db.flush()
        second_contribution = ActivityGoalContribution(user_id=user.id, activity_session_id=second.id, goal_id=goal.id, contribution_type="time", contribution_value=1800, unit="seconds")
        db.add(second_contribution)
        db.commit()
        overlap_summary = analytics_routes.summary(day, day, db, user)
        assert overlap_summary.totals.actual_seconds == 5400
        assert overlap_summary.totals.allocated_seconds == 0
        assert overlap_summary.totals.allocation_attribution_unavailable_seconds == 3600
        assert overlap_summary.totals.unallocated_seconds is None


def test_daily_report_unifies_profile_local_execution_without_double_counting(pg_sessions):
    with pg_sessions() as db:
        user = make_user(db, "Asia/Kolkata")
        day = date(2026, 2, 1)
        planned_start = datetime(2026, 2, 1, 4, 30, tzinfo=UTC)  # 10:00 profile local
        schedule = ScheduleItem(
            user_id=user.id, title="Planned block", scheduled_date=day,
            start_at=planned_start, end_at=planned_start + timedelta(hours=1), status="partial",
        )
        cancelled = ScheduleItem(
            user_id=user.id, title="Cancelled block", scheduled_date=day,
            start_at=planned_start + timedelta(hours=2), end_at=planned_start + timedelta(hours=3), status="cancelled",
        )
        task = Task(user_id=user.id, title="Report task", status="completed", due_at=planned_start + timedelta(minutes=30))
        task_due_later = Task(user_id=user.id, title="Later task", status="planned", due_at=planned_start + timedelta(days=1))
        schedule_later = ScheduleItem(
            user_id=user.id, title="Later schedule", scheduled_date=day + timedelta(days=1),
            start_at=planned_start + timedelta(days=1), end_at=planned_start + timedelta(days=1, hours=1), status="planned",
        )
        target = Target(user_id=user.id, title="Focus target", month=day.replace(day=1), metric_type="time", target_value=3600)
        diary = DiaryEntry(user_id=user.id, entry_date=day, accomplishments="Finished the work")
        db.add_all([schedule, cancelled, task, task_due_later, schedule_later, target, diary])
        db.flush()
        confirmed = ActivitySession(
            user_id=user.id, title="Confirmed work", started_at=planned_start + timedelta(minutes=30),
            ended_at=planned_start + timedelta(hours=1, minutes=30), duration_seconds=3600,
            status="confirmed", source_kind="manual", confidence=1,
        )
        corrected = ActivitySession(
            user_id=user.id, title="Corrected work", started_at=planned_start + timedelta(hours=1, minutes=30),
            ended_at=planned_start + timedelta(hours=2), duration_seconds=1800,
            status="corrected", source_kind="manual", confidence=1,
        )
        draft = ActivitySession(
            user_id=user.id, title="Unreviewed work", started_at=planned_start + timedelta(hours=2),
            ended_at=planned_start + timedelta(hours=2, minutes=15), duration_seconds=900,
            status="draft", source_kind="observed", confidence=0.5,
        )
        legacy = ActivityRecord(
            user_id=user.id, title="Legacy metric", activity_type="reading", metric_value=12,
            recorded_at=planned_start + timedelta(hours=2), details={},
        )
        db.add_all([confirmed, corrected, draft, legacy])
        db.flush()
        event_time = datetime(2026, 2, 1, 9, tzinfo=UTC)
        db.add(ActivityGoalContribution(
            user_id=user.id, activity_session_id=confirmed.id, target_id=target.id,
            contribution_type="time", contribution_value=1800, unit="seconds",
        ))
        db.add_all([
            ScheduleStatusEvent(user_id=user.id, schedule_item_id=schedule.id, previous_status="planned", new_status="partial", event_kind="changed", created_at=event_time),
            ScheduleStatusEvent(user_id=user.id, schedule_item_id=schedule_later.id, previous_status="planned", new_status="completed", event_kind="changed", created_at=event_time),
            TaskStatusEvent(user_id=user.id, task_id=task.id, previous_status="in_progress", new_status="completed", event_kind="changed", created_at=event_time),
            TaskStatusEvent(user_id=user.id, task_id=task_due_later.id, previous_status="planned", new_status="in_progress", event_kind="changed", created_at=event_time),
        ])
        db.commit()

        report = analytics_routes.daily_report(day, db, user)

        assert report.timezone == "Asia/Kolkata"
        assert report.planned.planned_seconds == 3600
        assert report.planned.scheduled_blocks == 1
        assert report.planned.cancelled_blocks == 1
        assert report.planned.completed_tasks == 1
        assert report.actual.confirmed_seconds == 3600
        assert report.actual.corrected_seconds == 1800
        assert report.actual.actual_seconds == 5400
        assert report.actual.draft_seconds == 900
        assert report.actual.outside_planned_seconds == 3600
        assert report.actual.allocated_seconds == 1800
        assert report.actual.unallocated_seconds == 3600
        assert report.actual.confirmed_session_count == 1
        assert report.actual.corrected_session_count == 1
        assert report.data_quality.legacy_activity_record_count == 1
        assert report.data_quality.draft_session_count == 1
        assert report.reflection.available is True
        assert len(report.historical_activities) == 1
        assert {item.status for item in report.activities} >= {"confirmed", "corrected", "draft"}
        assert len(report.goal_contributions) == 1
        assert len(report.schedule) == 2
        assert len(report.schedule_history) >= 2
        assert len(report.task_history) >= 2
        assert str(task_due_later.id) in {change.item_id for change in report.task_history}
        assert str(schedule_later.id) in {change.item_id for change in report.schedule_history}


def test_daily_report_empty_day_uses_profile_timezone_and_empty_sections(pg_sessions):
    with pg_sessions() as db:
        user = make_user(db, "UTC")
        report = analytics_routes.daily_report(date(2026, 6, 10), db, user)
        assert report.timezone == "UTC"
        assert report.actual.actual_seconds == 0
        assert report.actual.unallocated_seconds == 0
        assert report.planned.planned_seconds == 0
        assert report.activities == []
        assert report.goal_contributions == []
        assert report.reflection.available is False


def test_daily_report_uses_stopped_timer_segments_and_marks_legacy_time_unavailable(pg_sessions):
    with pg_sessions() as db:
        user = make_user(db, "UTC")
        day = date(2026, 6, 1)
        start = datetime(2026, 6, 1, 10, tzinfo=UTC)
        timer = TimeSession(
            user_id=user.id, title="Segmented timer", started_at=start,
            ended_at=start + timedelta(minutes=50), duration_seconds=1800, status="completed",
        )
        legacy_timer = TimeSession(
            user_id=user.id, title="Legacy timer", started_at=start + timedelta(hours=1),
            ended_at=start + timedelta(hours=1, minutes=20), duration_seconds=900, status="completed",
        )
        db.add_all([timer, legacy_timer])
        db.flush()
        segmented = ActivitySession(
            user_id=user.id, time_session_id=timer.id, title="Segmented timer", started_at=start,
            ended_at=start + timedelta(minutes=50), duration_seconds=1800, status="confirmed",
            source_kind="stopwatch", confidence=1,
        )
        legacy = ActivitySession(
            user_id=user.id, time_session_id=legacy_timer.id, title="Legacy timer", started_at=start + timedelta(hours=1),
            ended_at=start + timedelta(hours=1, minutes=20), duration_seconds=900, status="confirmed",
            source_kind="legacy", confidence=1,
        )
        db.add_all([segmented, legacy])
        db.flush()
        db.add_all([
            TimeSessionSegment(user_id=user.id, time_session_id=timer.id, started_at=start, ended_at=start + timedelta(minutes=10)),
            TimeSessionSegment(user_id=user.id, time_session_id=timer.id, started_at=start + timedelta(minutes=30), ended_at=start + timedelta(minutes=50)),
        ])
        db.commit()

        report = analytics_routes.daily_report(day, db, user)
        assert report.actual.actual_seconds == 1800
        assert report.actual.unavailable_legacy_seconds == 900
        assert report.data_quality.unavailable_legacy_seconds == 900
        assert next(row for row in report.activities if row.id == str(legacy.id)).duration_seconds is None


def test_daily_report_keeps_cross_midnight_allocation_attribution_unknown(pg_sessions):
    with pg_sessions() as db:
        user = make_user(db, "UTC")
        start = datetime(2026, 6, 1, 23, 30, tzinfo=UTC)
        session = ActivitySession(
            user_id=user.id, title="Midnight session", started_at=start,
            ended_at=start + timedelta(hours=1), duration_seconds=3600,
            status="confirmed", source_kind="manual", confidence=1,
        )
        target = Target(user_id=user.id, title="Time target", month=date(2026, 6, 1), metric_type="time", target_value=3600)
        db.add_all([session, target])
        db.flush()
        db.add(ActivityGoalContribution(
            user_id=user.id, activity_session_id=session.id, target_id=target.id,
            contribution_type="time", contribution_value=1200, unit="seconds",
        ))
        db.commit()

        first_day = analytics_routes.daily_report(date(2026, 6, 1), db, user)
        second_day = analytics_routes.daily_report(date(2026, 6, 2), db, user)
        assert first_day.actual.actual_seconds == 1800
        assert second_day.actual.actual_seconds == 1800
        assert first_day.actual.allocated_seconds == 0
        assert first_day.actual.unallocated_seconds is None
        assert first_day.actual.ambiguous_allocation_seconds == 1200
        assert second_day.actual.unallocated_seconds is None


def test_daily_report_boundaries_follow_dst_and_non_hour_offset_changes(pg_sessions):
    with pg_sessions() as db:
        new_york = make_user(db, "America/New_York")
        ny_start = datetime(2026, 3, 9, 3, 30, tzinfo=UTC)  # 23:30 EDT on March 8
        db.add(ActivitySession(
            user_id=new_york.id, title="DST midnight", started_at=ny_start,
            ended_at=ny_start + timedelta(hours=1), duration_seconds=3600,
            status="confirmed", source_kind="manual", confidence=1,
        ))

        lord_howe = make_user(db, "Australia/Lord_Howe")
        lh_start = datetime(2026, 10, 4, 12, 45, tzinfo=UTC)  # 23:45 local after the 30-minute DST change
        db.add(ActivitySession(
            user_id=lord_howe.id, title="Non-hour DST midnight", started_at=lh_start,
            ended_at=lh_start + timedelta(minutes=30), duration_seconds=1800,
            status="confirmed", source_kind="manual", confidence=1,
        ))
        db.commit()

        assert analytics_routes.daily_report(date(2026, 3, 8), db, new_york).actual.actual_seconds == 1800
        assert analytics_routes.daily_report(date(2026, 3, 9), db, new_york).actual.actual_seconds == 1800
        assert analytics_routes.daily_report(date(2026, 10, 4), db, lord_howe).actual.actual_seconds == 900
        assert analytics_routes.daily_report(date(2026, 10, 5), db, lord_howe).actual.actual_seconds == 900


def test_planned_vs_confirmed_actual_union_and_explicit_association(pg_sessions):
    with pg_sessions() as db:
        user = make_user(db)
        day = date(2026, 11, 17)
        start = datetime(2026, 11, 17, 10, tzinfo=UTC)
        block = ScheduleItem(user_id=user.id, title="Planned", scheduled_date=day, start_at=start, end_at=start + timedelta(hours=1))
        db.add(block)
        db.commit()
        other = make_user(db)
        other_block = ScheduleItem(user_id=other.id, title="Other block", scheduled_date=day, start_at=start, end_at=start + timedelta(hours=1))
        db.add(other_block)
        db.commit()
        before = schedule_routes.execution_summary(day, day, db, user)
        assert before.items[0].planned_seconds == 3600
        assert before.items[0].confirmed_actual_seconds == 0

        first = activity_routes.create_activity_session(ActivitySessionCreate(
            title="Manual interval A", started_at=start, ended_at=start + timedelta(minutes=30), duration_seconds=1800,
        ), db, user)
        second = activity_routes.create_activity_session(ActivitySessionCreate(
            title="Manual interval B", started_at=start + timedelta(minutes=15), ended_at=start + timedelta(minutes=45), duration_seconds=1800,
        ), db, user)
        draft = ActivitySession(user_id=user.id, title="Unconfirmed", schedule_item_id=block.id, started_at=start, ended_at=start + timedelta(minutes=20), duration_seconds=1200, status="draft", source_kind="observed")
        discarded = ActivitySession(user_id=user.id, title="Discarded", schedule_item_id=block.id, started_at=start, ended_at=start + timedelta(minutes=10), duration_seconds=600, status="discarded", source_kind="manual")
        db.add_all([draft, discarded])
        db.commit()
        activity_routes.update_associations(first.id, ActivityAssociationUpdate(schedule_item_id=block.id), db, user)
        activity_routes.update_associations(second.id, ActivityAssociationUpdate(schedule_item_id=block.id), db, user)
        with pytest.raises(HTTPException) as cross_user:
            activity_routes.update_associations(first.id, ActivityAssociationUpdate(schedule_item_id=other_block.id), db, user)
        assert cross_user.value.status_code == 404
        result = schedule_routes.execution_summary(day, day, db, user)
        assert result.items[0].confirmed_actual_seconds == 2700
        assert result.items[0].confirmed_session_count == 2
        assert result.totals.associated_actual_seconds == 2700
        assert first.schedule_item_id == block.id


def test_stopwatch_keeps_schedule_link_and_needs_confirmation(pg_sessions):
    with pg_sessions() as db:
        user = make_user(db)
        now = datetime.now(UTC).replace(microsecond=0)
        block = ScheduleItem(user_id=user.id, title="Timer block", scheduled_date=now.date(), start_at=now-timedelta(minutes=5), end_at=now+timedelta(minutes=55))
        db.add(block)
        db.flush()
        timer = TimeSession(user_id=user.id, schedule_item_id=block.id, title="Timer block", started_at=now-timedelta(minutes=30), duration_seconds=600, status="paused")
        db.add(timer)
        db.flush()
        db.add(TimeSessionSegment(time_session_id=timer.id, user_id=user.id, started_at=now-timedelta(minutes=30), ended_at=now-timedelta(minutes=20)))
        db.commit()
        timer_routes.stop(timer.id, db, user)
        activity = db.scalar(select(ActivitySession).where(ActivitySession.time_session_id == timer.id))
        assert activity.schedule_item_id == block.id
        assert activity.duration_seconds == 600
        assert activity.status == "draft"
        result = schedule_routes.execution_summary(now.date(), now.date(), db, user)
        assert result.items[0].confirmed_actual_seconds == 0
        activity_routes.confirm_session(activity.id, db, user)
        assert schedule_routes.execution_summary(now.date(), now.date(), db, user).items[0].confirmed_actual_seconds == 600


def test_concurrent_schedule_create_cannot_bypass_conflict_check(pg_sessions):
    with pg_sessions() as db:
        user = make_user(db)
        user_id = user.id
        db.commit()
    day = date(2026, 8, 10)
    payload = schedule_payload(day, datetime(2026, 8, 10, 12), datetime(2026, 8, 10, 13))

    def create_one():
        with pg_sessions() as db:
            user = db.get(User, user_id)
            try:
                schedule_routes.create(payload, db, user)
                return "created"
            except HTTPException as exc:
                assert exc.status_code == 409
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: create_one(), range(2)))
    assert sorted(results) == ["conflict", "created"]


def test_schedule_range_retrieval_and_date_move(pg_sessions):
    with pg_sessions() as db:
        user = make_user(db)
        first = date(2026, 11, 16)
        start = datetime(2026, 11, 16, 9, tzinfo=UTC)
        block = schedule_routes.create(schedule_payload(first, start, start + timedelta(hours=1)), db, user, allow_conflict=True)
        next_day = first + timedelta(days=1)
        updated = schedule_routes.update(block.id, ScheduleItemUpdate(scheduled_date=next_day), db, user, allow_conflict=True)
        assert updated.scheduled_date == next_day
        assert updated.start_at == datetime(2026, 11, 17, 9, tzinfo=UTC)
        assert schedule_routes.list_schedule(start_date=first, end_date=next_day, db=db, user=user) == [updated]
        with pytest.raises(HTTPException) as invalid_range:
            schedule_routes.list_schedule(start_date=first, end_date=first - timedelta(days=1), db=db, user=user)
        assert invalid_range.value.status_code == 422


def test_routine_occurrence_identity_idempotence_and_deactivation(pg_sessions):
    with pg_sessions() as db:
        user = make_user(db)
        other = make_user(db)
        other_task = Task(user_id=other.id, title="Private task")
        db.add(other_task)
        db.commit()
        cross_user = RoutineTemplate(
            user_id=user.id, title="Invalid ownership", weekdays=[0], start_time=datetime.strptime("08:00", "%H:%M").time(),
            end_time=datetime.strptime("09:00", "%H:%M").time(), task_id=other_task.id,
        )
        with pytest.raises(IntegrityError):
            with db.begin_nested():
                db.add(cross_user)
                db.flush()
        db.rollback()
        user = db.get(User, user.id)
        day = date(2026, 11, 16)
        routine = RoutineTemplate(
            user_id=user.id, title="Reading", weekdays=[0], start_time=datetime.strptime("09:00", "%H:%M").time(),
            end_time=datetime.strptime("10:00", "%H:%M").time(),
        )
        db.add(routine)
        db.commit()
        assert routine_routes.generate(day, db, user).created_count == 1
        assert routine_routes.generate(day, db, user).created_count == 0
        occurrence = db.scalar(select(ScheduleItem).where(ScheduleItem.routine_template_id == routine.id))
        routine_routes.update(routine.id, RoutineTemplateUpdate(title="New reading time"), db, user)
        db.expire_all()
        assert db.get(ScheduleItem, occurrence.id).title == "Reading"
        routine_routes.delete(routine.id, db, user)
        assert routine_routes.generate(day, db, user).created_count == 0
        assert db.get(ScheduleItem, occurrence.id).routine_template_id == routine.id


def test_concurrent_routine_generation_is_idempotent(pg_sessions):
    with pg_sessions() as db:
        user = make_user(db)
        user_id = user.id
        routine = RoutineTemplate(
            user_id=user.id, title="Morning plan", weekdays=[0], start_time=datetime.strptime("09:00", "%H:%M").time(),
            end_time=datetime.strptime("10:00", "%H:%M").time(),
        )
        db.add(routine)
        db.commit()
    day = date(2026, 11, 16)

    def generate_once():
        with pg_sessions() as db:
            user = db.get(User, user_id)
            return routine_routes.generate(day, db, user).created_count

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: generate_once(), range(2)))
    assert sorted(results) == [0, 1]

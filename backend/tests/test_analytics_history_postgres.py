"""PostgreSQL coverage for bounded historical reports and goal history."""

import os
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models import (
    ActivityGoalContribution, ActivitySession, Ambition, AmbitionGoal,
    AmbitionMilestone, DiaryEntry, GoalProgressEntry, ScheduleItem, Task,
    User, UserProfile,
)
from app.api.v1.routes import analytics as analytics_routes


POSTGRES_TEST_URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_TEST_URL, reason="requires a dedicated disposable PostgreSQL database")


@pytest.fixture
def pg_sessions():
    admin = create_engine(POSTGRES_TEST_URL)
    schema = f"analytics_history_{uuid4().hex}"
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


def make_user(db, timezone="Asia/Kolkata"):
    user = User(id=uuid4(), username=f"history-{uuid4()}", email=f"{uuid4()}@example.test", password_hash="unused")
    db.add(user)
    db.flush()
    db.add(UserProfile(user_id=user.id, timezone=timezone))
    db.flush()
    return user


def test_empty_week_and_leap_month_use_calendar_periods_and_zero_baselines(pg_sessions):
    with pg_sessions() as db:
        user = make_user(db, "America/New_York")
        empty_week = analytics_routes.weekly_report(date(2024, 2, 26), db, user)
        assert empty_week.end_date == date(2024, 3, 3)
        assert len(empty_week.daily) == 7
        assert empty_week.days_with_no_recorded_activity == 7
        assert empty_week.totals.actual_seconds == 0
        assert empty_week.comparison["confirmed_actual_seconds"].previous == 0
        assert empty_week.comparison["confirmed_actual_seconds"].percent_change is None

        leap_month = analytics_routes.monthly_report("2024-02", db, user)
        assert leap_month.start_date == date(2024, 2, 1)
        assert leap_month.end_date == date(2024, 2, 29)
        assert len(leap_month.daily) == 29
        assert leap_month.reflection_coverage_percent == 0
        assert len(analytics_routes.monthly_report("2023-02", db, user).daily) == 28
        assert len(analytics_routes.monthly_report("2026-11", db, user).daily) == 30

        dst_session = ActivitySession(
            user_id=user.id, title="DST crossing", started_at=datetime(2024, 3, 10, 6, 30, tzinfo=UTC),
            ended_at=datetime(2024, 3, 10, 7, 30, tzinfo=UTC), duration_seconds=3600,
            confidence=1, status="confirmed", source_kind="manual",
        )
        db.add(dst_session)
        db.commit()
        dst_week = analytics_routes.weekly_report(date(2024, 3, 4), db, user)
        dst_day = next(day for day in dst_week.daily if day.date == date(2024, 3, 10))
        assert dst_day.actual_seconds == 3600  # 01:30 EST to 03:30 EDT is one elapsed hour.
        assert analytics_routes.monthly_report("2024-03", db, user).totals.actual_seconds == 3600

        with pytest.raises(HTTPException) as invalid_week:
            analytics_routes.weekly_report(date(2024, 2, 27), db, user)
        assert invalid_week.value.status_code == 422


def test_period_totals_reconcile_and_goal_history_keeps_corrections_and_reversals(pg_sessions):
    with pg_sessions() as db:
        user = make_user(db)
        other_user = make_user(db, "UTC")
        ambition = Ambition(user_id=user.id, title="Read more", category="learning", start_date=date(2026, 11, 1))
        other_ambition = Ambition(user_id=other_user.id, title="Private", category="learning")
        db.add_all([ambition, other_ambition])
        db.flush()
        goal = AmbitionGoal(user_id=user.id, ambition_id=ambition.id, title="Read books", measurement_type="count", measurement_unit="books", current_value=Decimal("2"))
        other_goal = AmbitionGoal(user_id=other_user.id, ambition_id=other_ambition.id, title="Other", measurement_type="count", measurement_unit="books")
        db.add_all([goal, other_goal])
        db.flush()

        start = datetime(2026, 11, 14, 3, 30, tzinfo=UTC)  # 09:00 in the profile timezone.
        end = start + timedelta(hours=1)
        schedule = ScheduleItem(user_id=user.id, title="Reading", scheduled_date=date(2026, 11, 14), start_at=start, end_at=end, status="completed")
        task = Task(user_id=user.id, title="Read a chapter", due_at=start, status="completed", priority=2)
        session = ActivitySession(user_id=user.id, title="Reading", started_at=start, ended_at=end, duration_seconds=3600, confidence=1, status="confirmed", source_kind="manual")
        corrected = ActivitySession(user_id=user.id, title="Corrected reading", started_at=start + timedelta(minutes=30), ended_at=start + timedelta(minutes=40), duration_seconds=600, confidence=1, status="corrected", source_kind="manual")
        overnight_start = datetime(2026, 11, 14, 18, tzinfo=UTC)  # 23:30–00:30 in Asia/Kolkata.
        overnight = ActivitySession(user_id=user.id, title="Midnight reading", started_at=overnight_start, ended_at=overnight_start + timedelta(hours=1), duration_seconds=3600, confidence=1, status="confirmed", source_kind="manual")
        db.add_all([schedule, task, session, corrected, overnight])
        db.flush()
        session.schedule_item_id = schedule.id
        corrected.schedule_item_id = schedule.id
        event_time = datetime(2026, 11, 14, 5, tzinfo=UTC)
        contribution = ActivityGoalContribution(user_id=user.id, activity_session_id=session.id, goal_id=goal.id, contribution_type="metric", contribution_value=Decimal("1"), unit="books", created_at=event_time)
        entry = GoalProgressEntry(user_id=user.id, goal_id=goal.id, numeric_delta=Decimal("1"), resulting_value=Decimal("2"), unit="books", source_kind="activity", source_contribution_id=uuid4(), created_at=event_time)
        milestone = AmbitionMilestone(user_id=user.id, goal_id=goal.id, title="Finish one book", status="completed", completed_at=date(2026, 11, 14))
        diary = DiaryEntry(user_id=user.id, entry_date=date(2026, 11, 14), learned="A new idea")
        db.add_all([contribution, entry, milestone, diary])
        db.commit()
        correction = GoalProgressEntry(user_id=user.id, goal_id=goal.id, numeric_delta=Decimal("-1"), resulting_value=Decimal("1"), unit="books", source_kind="correction", corrects_entry_id=entry.id, reason="Duplicate progress entry", created_at=event_time + timedelta(minutes=1))
        contribution.reversed_at = event_time + timedelta(minutes=1)
        db.add(correction)
        db.commit()

        report = analytics_routes.weekly_report(date(2026, 11, 9), db, user)
        assert report.totals.actual_seconds == sum(day.actual_seconds for day in report.daily) == 7200
        assert report.totals.confirmed_seconds == 7200
        assert report.totals.corrected_seconds == 600
        assert report.totals.ambiguous_actual_seconds == 600
        execution = analytics_routes.schedule_execution_summary(date(2026, 11, 9), date(2026, 11, 15), db, user)
        assert report.totals.actual_seconds == execution.totals.confirmed_actual_seconds == 7200
        assert report.totals.planned_seconds == execution.totals.planned_seconds
        assert report.outside_planned_seconds == execution.totals.outside_planned_seconds == 3600
        daily_reports = [analytics_routes.daily_report(day.date, db, user) for day in report.daily]
        assert report.totals.actual_seconds == sum(item.actual.actual_seconds for item in daily_reports)
        assert report.totals.planned_seconds == sum(item.planned.planned_seconds for item in daily_reports)
        assert report.totals.planned_seconds == sum(day.planned_seconds for day in report.daily) == 3600
        assert report.days_with_confirmed_or_corrected_activity == 2
        assert report.days_with_planned_activity == 1
        assert report.task_status_transitions["completed"] == 1
        assert report.contribution_count == 1
        assert len(report.progress_entries) == 2
        assert len(report.milestones) == 1
        assert report.reflection_days == 1
        nov14 = next(item for item in daily_reports if item.date == date(2026, 11, 14))
        nov15 = next(item for item in daily_reports if item.date == date(2026, 11, 15))
        assert nov14.actual.actual_seconds == 5400
        assert nov15.actual.actual_seconds == 1800
        monthly = analytics_routes.monthly_report("2026-11", db, user)
        assert monthly.totals.actual_seconds == sum(day.actual_seconds for day in monthly.daily)
        assert monthly.totals.planned_seconds == sum(day.planned_seconds for day in monthly.daily)
        weekly_november_actual = 0
        weekly_november_planned = 0
        for monday in (date(2026, 10, 26), date(2026, 11, 2), date(2026, 11, 9), date(2026, 11, 16), date(2026, 11, 23), date(2026, 11, 30)):
            weekly = analytics_routes.weekly_report(monday, db, user)
            november_days = [day for day in weekly.daily if date(2026, 11, 1) <= day.date <= date(2026, 11, 30)]
            weekly_november_actual += sum(day.actual_seconds for day in november_days)
            weekly_november_planned += sum(day.planned_seconds for day in november_days)
        assert weekly_november_actual == monthly.totals.actual_seconds
        assert weekly_november_planned == monthly.totals.planned_seconds

        history = analytics_routes.goal_history(goal.id, date(2026, 11, 9), date(2026, 11, 15), db, user)
        assert history.starting_value is None
        assert history.starting_value_status == "not_recorded"
        assert history.progress_entries[0].resulting_value == "2.0000"
        assert history.progress_entries[1].corrects_entry_id == str(entry.id)
        assert history.contributions[0].value == "1.0000"
        assert history.contributions[0].reversed_at is not None
        with pytest.raises(HTTPException) as denied:
            analytics_routes.goal_history(other_goal.id, None, None, db, user)
        assert denied.value.status_code == 404

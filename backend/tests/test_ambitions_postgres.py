"""PostgreSQL persistence, ownership, audit, and contribution checks for ambitions."""

import os
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, func, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models import (
    ActivityGoalContribution, ActivitySession, Ambition, AmbitionGoal,
    AmbitionLifecycleEvent, AmbitionMilestone, GoalProgressEntry, Project, Target, User,
)
from app.schemas.activity_session import ContributionInput, ContributionSet, SplitRequest, MergeRequest
from app.schemas.ambition import (
    AmbitionCreate, AmbitionLifecycle, GoalCreate, GoalProgressCorrection,
    GoalProgressCreate, MilestoneCreate, MilestoneUpdate,
)
from app.schemas.target import TargetCreate
import app.api.v1.routes.ambitions as ambition_routes
import app.api.v1.routes.activity_sessions as activity_routes
import app.api.v1.routes.targets as target_routes
import app.api.v1.routes.projects as project_routes
from app.schemas.project import ProjectCreate


POSTGRES_TEST_URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_TEST_URL, reason="requires a dedicated disposable PostgreSQL database")


@pytest.fixture
def pg_sessions():
    admin = create_engine(POSTGRES_TEST_URL)
    schema = f"ambition_test_{uuid4().hex}"
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


def make_user(db):
    user = User(id=uuid4(), username=f"amb-{uuid4()}", email=f"{uuid4()}@example.test", password_hash="unused")
    db.add(user)
    db.flush()
    return user


def make_ambition(db, user, title="Long horizon"):
    return ambition_routes.create_ambition(AmbitionCreate(title=title, category="learning"), db, user)


def make_goal(db, user, ambition, title="Measured goal", measure="count", unit="books"):
    return ambition_routes.create_goal(ambition.id, GoalCreate(title=title, measurement_type=measure, measurement_unit=unit), db, user)


def test_ambition_lifecycle_hierarchy_and_user_scoped_ownership(pg_sessions):
    with pg_sessions() as db:
        user = make_user(db)
        ambition = make_ambition(db, user)
        goal = make_goal(db, user, ambition)
        paused = ambition_routes.set_ambition_lifecycle(ambition.id, AmbitionLifecycle(status="paused"), db, user)
        assert paused.status == "paused"
        completed = ambition_routes.set_ambition_lifecycle(ambition.id, AmbitionLifecycle(status="completed"), db, user)
        assert completed.status == "completed" and completed.completed_at is not None
        restored = ambition_routes.set_ambition_lifecycle(ambition.id, AmbitionLifecycle(status="active"), db, user)
        assert restored.status == "active" and restored.completed_at is None
        lifecycle_rows = list(db.scalars(select(AmbitionLifecycleEvent).where(AmbitionLifecycleEvent.ambition_id == ambition.id).order_by(AmbitionLifecycleEvent.created_at)).all())
        assert [row.new_status for row in lifecycle_rows] == ["paused", "completed", "active"]
        with pytest.raises(SQLAlchemyError):
            with db.begin_nested():
                db.execute(update(AmbitionLifecycleEvent).where(AmbitionLifecycleEvent.id == lifecycle_rows[0].id).values(reason="rewrite"))
        other = make_user(db)
        with pytest.raises(Exception) as err:
            ambition_routes.owned_ambition(db, ambition.id, other.id)
        assert getattr(err.value, "status_code", None) == 404
        with pytest.raises(IntegrityError):
            with db.begin_nested():
                db.add(AmbitionGoal(user_id=other.id, ambition_id=ambition.id, title="cross-user", measurement_type="count"))
                db.flush()
        assert goal.ambition_id == ambition.id


def test_measurements_progress_corrections_milestones_and_immutable_history(pg_sessions):
    with pg_sessions() as db:
        user = make_user(db)
        ambition = make_ambition(db, user)
        goal = make_goal(db, user, ambition, measure="distance", unit="km")
        first = ambition_routes.record_goal_progress(goal.id, GoalProgressCreate(numeric_delta=Decimal("12.5"), unit="km", reason="Training log"), db, user)
        with pytest.raises(Exception) as invalid:
            ambition_routes.record_goal_progress(goal.id, GoalProgressCreate(numeric_delta=Decimal("1"), unit="miles"), db, user)
        assert getattr(invalid.value, "status_code", None) == 422
        corrected = ambition_routes.correct_goal_progress(goal.id, first.id, GoalProgressCorrection(numeric_delta=Decimal("-2.5"), unit="km", reason="Duplicate distance correction"), db, user)
        assert corrected.source_kind == "correction" and corrected.corrects_entry_id == first.id
        assert goal.current_value == Decimal("10.0000")

        count_goal = make_goal(db, user, ambition, title="Books finished", measure="count", unit="books")
        milestone = ambition_routes.create_milestone(count_goal.id, MilestoneCreate(title="Finish first book"), db, user)
        complete = ambition_routes.update_milestone(milestone.id, MilestoneUpdate(status="completed"), db, user)
        assert complete.status == "completed" and count_goal.current_value == Decimal("1")
        reopened = ambition_routes.update_milestone(milestone.id, MilestoneUpdate(status="open"), db, user)
        assert reopened.status == "open" and count_goal.current_value == Decimal("0")
        history = list(db.scalars(select(GoalProgressEntry).where(GoalProgressEntry.goal_id == count_goal.id).order_by(GoalProgressEntry.created_at)).all())
        assert len(history) == 2 and history[1].corrects_entry_id == history[0].id
        with pytest.raises(SQLAlchemyError):
            with db.begin_nested():
                db.execute(update(GoalProgressEntry).where(GoalProgressEntry.id == first.id).values(reason="rewrite"))


def test_existing_targets_can_be_weekly_or_monthly_and_archive_keeps_goal_history(pg_sessions):
    with pg_sessions() as db:
        user = make_user(db)
        ambition = make_ambition(db, user)
        goal = make_goal(db, user, ambition)
        weekly = target_routes.create_target(TargetCreate(title="This week", month=date(2026, 11, 9), period_type="weekly", ambition_goal_id=goal.id), db, user)
        monthly = target_routes.create_target(TargetCreate(title="This month", month=date(2026, 11, 1), period_type="monthly", ambition_goal_id=goal.id), db, user)
        assert weekly.period_type == "weekly" and monthly.period_type == "monthly"
        entry = ambition_routes.record_goal_progress(goal.id, GoalProgressCreate(numeric_delta=Decimal(2), unit="books"), db, user)
        ambition_routes.set_ambition_lifecycle(ambition.id, AmbitionLifecycle(status="archived"), db, user)
        assert db.scalar(select(func.count()).select_from(AmbitionGoal).where(AmbitionGoal.id == goal.id)) == 1
        assert db.scalar(select(func.count()).select_from(GoalProgressEntry).where(GoalProgressEntry.id == entry.id)) == 1
        assert db.scalar(select(func.count()).select_from(Target).where(Target.ambition_goal_id == goal.id)) == 2


def test_activity_contributions_span_goals_with_one_session_time_budget(pg_sessions):
    with pg_sessions() as db:
        user = make_user(db)
        ambition_a = make_ambition(db, user, "Training")
        ambition_b = make_ambition(db, user, "Learning")
        time_a = make_goal(db, user, ambition_a, "Practice time", "duration", "seconds")
        time_b = make_goal(db, user, ambition_b, "Study time", "duration", "seconds")
        metric_goal = make_goal(db, user, ambition_b, "Problems solved", "count", "problems")
        now = datetime.now(UTC)
        session = ActivitySession(user_id=user.id, title="Focus", started_at=now - timedelta(seconds=130), ended_at=now, duration_seconds=100, status="confirmed", source_kind="manual")
        db.add(session); db.commit(); db.refresh(session)
        with pytest.raises(Exception) as overallocated:
            activity_routes.add_contributions(session.id, ContributionSet(contributions=[
                ContributionInput(goal_id=time_a.id, contribution_type="time", contribution_value=Decimal(60), unit="seconds"),
                ContributionInput(goal_id=time_b.id, contribution_type="time", contribution_value=Decimal(50), unit="seconds"),
            ]), db, user)
        assert getattr(overallocated.value, "status_code", None) == 409
        created = activity_routes.add_contributions(session.id, ContributionSet(contributions=[
            ContributionInput(goal_id=time_a.id, contribution_type="time", contribution_value=Decimal(50), unit="seconds"),
            ContributionInput(goal_id=time_b.id, contribution_type="time", contribution_value=Decimal(50), unit="seconds"),
        ]), db, user)
        assert len(created) == 2 and time_a.current_value == Decimal(50) and time_b.current_value == Decimal(50)
        activity_routes.remove_contribution(session.id, created[0]["id"], "Reallocate the measured time", db, user)
        reversed_row = db.get(ActivityGoalContribution, created[0]["id"])
        assert reversed_row is not None and reversed_row.reversed_at is not None
        assert time_a.current_value == Decimal(0)
        activity_routes.add_contributions(session.id, ContributionSet(contributions=[
            ContributionInput(goal_id=time_a.id, contribution_type="time", contribution_value=Decimal(50), unit="seconds"),
        ]), db, user)
        assert db.scalar(select(func.sum(ActivityGoalContribution.contribution_value)).where(ActivityGoalContribution.activity_session_id == session.id, ActivityGoalContribution.contribution_type == "time", ActivityGoalContribution.reversed_at.is_(None))) == Decimal(100)
        duplicate_session = ActivitySession(user_id=user.id, title="Duplicate guard", started_at=now - timedelta(seconds=130), ended_at=now, duration_seconds=100, status="confirmed")
        db.add(duplicate_session); db.commit(); db.refresh(duplicate_session)
        activity_routes.add_contributions(duplicate_session.id, ContributionSet(contributions=[
            ContributionInput(goal_id=time_a.id, contribution_type="time", contribution_value=Decimal(10), unit="seconds"),
        ]), db, user)
        with pytest.raises(Exception) as duplicate:
            activity_routes.add_contributions(duplicate_session.id, ContributionSet(contributions=[
                ContributionInput(goal_id=time_a.id, contribution_type="time", contribution_value=Decimal(20), unit="seconds"),
            ]), db, user)
        assert getattr(duplicate.value, "status_code", None) == 409

        metric_session = ActivitySession(user_id=user.id, title="DSA practice", started_at=now - timedelta(seconds=20), ended_at=now, duration_seconds=10, status="confirmed", source_kind="manual")
        db.add(metric_session); db.commit(); db.refresh(metric_session)
        metric_row = activity_routes.add_contributions(metric_session.id, ContributionSet(contributions=[
            ContributionInput(goal_id=metric_goal.id, contribution_type="metric", contribution_value=Decimal(5), unit="problems"),
        ]), db, user)[0]
        progress = db.scalar(select(GoalProgressEntry).where(GoalProgressEntry.source_contribution_id == metric_row["id"]))
        assert progress is not None and progress.source_kind == "activity" and progress.details["activity_session_id"] == str(metric_session.id)


def test_time_goal_contributions_survive_activity_split_and_merge(pg_sessions):
    with pg_sessions() as db:
        user = make_user(db)
        ambition = make_ambition(db, user)
        goal = make_goal(db, user, ambition, "Focus", "duration", "seconds")
        now = datetime.now(UTC)
        parent = ActivitySession(user_id=user.id, title="Long work", started_at=now - timedelta(seconds=130), ended_at=now, duration_seconds=100, status="confirmed")
        db.add(parent); db.flush()
        db.add(ActivityGoalContribution(user_id=user.id, activity_session_id=parent.id, target_id=None, goal_id=goal.id, contribution_type="time", contribution_value=Decimal(60), unit="seconds"))
        db.commit()
        parent_id = parent.id
        user_id = user.id
        split_at = parent.started_at + timedelta(seconds=50)
        children = activity_routes.split_session(parent_id, SplitRequest(split_at=split_at, reason="Separate blocks"), db, user)
        assert sum(child.duration_seconds for child in children) == 100
        child_total = db.scalar(select(func.sum(ActivityGoalContribution.contribution_value)).where(ActivityGoalContribution.activity_session_id.in_([child.id for child in children]), ActivityGoalContribution.goal_id == goal.id))
        assert child_total == Decimal(60)

        left = ActivitySession(user_id=user_id, title="Earlier", started_at=now - timedelta(hours=2), ended_at=now - timedelta(hours=2) + timedelta(seconds=40), duration_seconds=20, status="confirmed")
        right = ActivitySession(user_id=user_id, title="Later", started_at=now - timedelta(hours=1), ended_at=now - timedelta(hours=1) + timedelta(seconds=40), duration_seconds=30, status="confirmed")
        db.add_all([left, right]); db.flush()
        db.add_all([
            ActivityGoalContribution(user_id=user_id, activity_session_id=left.id, target_id=None, goal_id=goal.id, contribution_type="time", contribution_value=Decimal(10), unit="seconds"),
            ActivityGoalContribution(user_id=user_id, activity_session_id=right.id, target_id=None, goal_id=goal.id, contribution_type="time", contribution_value=Decimal(20), unit="seconds"),
        ])
        db.commit()
        merged = activity_routes.merge_session(left.id, MergeRequest(other_session_id=right.id, reason="One goal period"), db, user)
        assert db.scalar(select(func.sum(ActivityGoalContribution.contribution_value)).where(ActivityGoalContribution.activity_session_id == merged.id, ActivityGoalContribution.goal_id == goal.id)) == Decimal(30)


def test_project_delete_unlinks_goal_and_preserves_ambition_history(pg_sessions):
    with pg_sessions() as db:
        user = make_user(db)
        ambition = make_ambition(db, user, "Build expertise")
        linked_project = project_routes.create(ProjectCreate(name="Linked project"), db, user)
        unrelated_project = project_routes.create(ProjectCreate(name="Unrelated project"), db, user)
        linked_goal = make_goal(db, user, ambition, "Complete projects", "count", "projects")
        unrelated_goal = make_goal(db, user, ambition, "Read books", "count", "books")
        linked_goal.supporting_project_id = linked_project.id
        unrelated_goal.supporting_project_id = unrelated_project.id
        db.commit()

        manual_entry = ambition_routes.record_goal_progress(
            linked_goal.id,
            GoalProgressCreate(numeric_delta=Decimal(1), unit="projects", reason="Project completed"),
            db,
            user,
        )
        now = datetime.now(UTC)
        source_session = ActivitySession(
            user_id=user.id,
            title="Project work",
            started_at=now - timedelta(minutes=10),
            ended_at=now,
            duration_seconds=600,
            status="confirmed",
            source_kind="manual",
        )
        db.add(source_session)
        db.commit()
        metric = activity_routes.add_contributions(
            source_session.id,
            ContributionSet(contributions=[
                ContributionInput(
                    goal_id=linked_goal.id,
                    contribution_type="metric",
                    contribution_value=Decimal(1),
                    unit="projects",
                ),
            ]),
            db,
            user,
        )[0]
        contribution_id = metric["id"]
        progress_ids = set(db.scalars(
            select(GoalProgressEntry.id).where(GoalProgressEntry.goal_id == linked_goal.id)
        ).all())
        assert manual_entry.id in progress_ids
        assert db.scalar(select(GoalProgressEntry.id).where(
            GoalProgressEntry.source_contribution_id == contribution_id
        )) is not None

        result = project_routes.delete(linked_project.id, db, user)

        assert result is None
        db.expire_all()
        assert db.get(Project, linked_project.id) is None
        assert db.get(AmbitionGoal, linked_goal.id) is not None
        assert db.get(AmbitionGoal, linked_goal.id).supporting_project_id is None
        assert db.get(AmbitionGoal, unrelated_goal.id).supporting_project_id == unrelated_project.id
        assert db.get(Project, unrelated_project.id) is not None
        assert set(db.scalars(
            select(GoalProgressEntry.id).where(GoalProgressEntry.goal_id == linked_goal.id)
        ).all()) == progress_ids
        assert db.get(ActivityGoalContribution, contribution_id) is not None

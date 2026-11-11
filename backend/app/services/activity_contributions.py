"""Transactional activity contribution accounting."""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.activity_goal_contribution import ActivityGoalContribution
from app.models.activity_session import ActivitySession
from app.models.target import Target


def allocate_time(
    db: Session, *, user_id: UUID, activity_session_id: UUID, target_id: UUID,
    seconds: int, details: dict | None = None,
) -> ActivityGoalContribution:
    """Allocate seconds while holding the owning activity row lock until commit."""
    if seconds <= 0:
        raise ValueError("Time allocation must be positive")
    activity = db.execute(
        select(ActivitySession)
        .where(ActivitySession.id == activity_session_id, ActivitySession.user_id == user_id)
        .with_for_update()
    ).scalar_one()
    if activity.duration_seconds is None or activity.status not in {"confirmed", "corrected"}:
        raise ValueError("Only completed activity sessions can allocate time")
    target = db.execute(
        select(Target).where(Target.id == target_id, Target.user_id == user_id)
    ).scalar_one()
    if target.metric_type not in {"time", "seconds", "duration"}:
        raise ValueError("Target is not a time goal")
    allocated = db.execute(
        select(func.coalesce(func.sum(ActivityGoalContribution.contribution_value), 0)).where(
            ActivityGoalContribution.activity_session_id == activity_session_id,
            ActivityGoalContribution.contribution_type == "time",
        )
    ).scalar_one()
    if Decimal(allocated) + Decimal(seconds) > Decimal(activity.duration_seconds):
        raise ValueError("Time allocations exceed activity duration")
    contribution = ActivityGoalContribution(
        user_id=user_id, activity_session_id=activity_session_id, target_id=target_id,
        contribution_type="time", contribution_value=Decimal(seconds), unit="seconds",
        details=details or {},
    )
    db.add(contribution)
    db.flush()
    return contribution


def record_metric(
    db: Session, *, user_id: UUID, activity_session_id: UUID, target_id: UUID,
    value: Decimal, unit: str, details: dict | None = None,
) -> ActivityGoalContribution:
    """Record a metric without counting it as time allocation."""
    activity = db.execute(
        select(ActivitySession).where(
            ActivitySession.id == activity_session_id, ActivitySession.user_id == user_id
        )
    ).scalar_one()
    target = db.execute(select(Target).where(Target.id == target_id, Target.user_id == user_id)).scalar_one()
    if target.metric_type in {"time", "seconds", "duration"}:
        raise ValueError("Metric contributions cannot target a time goal")
    contribution = ActivityGoalContribution(
        user_id=user_id, activity_session_id=activity.id, target_id=target_id,
        contribution_type="metric", contribution_value=value, unit=unit, details=details or {},
    )
    db.add(contribution)
    db.flush()
    return contribution


def record_milestone(
    db: Session, *, user_id: UUID, activity_session_id: UUID, target_id: UUID,
    completed: bool = True, details: dict | None = None,
) -> ActivityGoalContribution:
    activity = db.execute(
        select(ActivitySession).where(
            ActivitySession.id == activity_session_id, ActivitySession.user_id == user_id
        )
    ).scalar_one()
    target = db.execute(select(Target).where(Target.id == target_id, Target.user_id == user_id)).scalar_one()
    if target.metric_type != "milestones_completed":
        raise ValueError("Milestone contributions require a milestone target")
    contribution = ActivityGoalContribution(
        user_id=user_id, activity_session_id=activity.id, target_id=target_id,
        contribution_type="milestone", contribution_value=Decimal(int(completed)),
        unit=None, details=details or {},
    )
    db.add(contribution)
    db.flush()
    return contribution

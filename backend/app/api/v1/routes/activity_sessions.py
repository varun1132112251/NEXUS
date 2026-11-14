from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import get_current_user
from app.db.session import get_db
from app.models.activity_correction import ActivityCorrection
from app.models.activity_event import ActivityEvent
from app.models.activity_goal_contribution import ActivityGoalContribution
from app.models.activity_session import ActivitySession
from app.models.activity_session_event import ActivitySessionEvent
from app.models.activity_source import ActivitySource
from app.models.target import Target
from app.models.schedule import ScheduleItem
from app.models.task import Task
from app.models.habit import Habit
from app.models.project import Project
from app.models.user import User
from app.schemas.activity_session import (
    ActivityEventWithSource,
    ActivitySessionCorrectionRequest,
    ActivityAssociationUpdate,
    ActivitySessionCreate,
    ActivitySessionRead,
    ActivityCorrectionRead,
    ContributionSet,
    SplitRequest,
    MergeRequest,
)
from app.models.activity_session_lineage import ActivitySessionLineage
from app.models.ambition_goal import AmbitionGoal
from app.models.goal_progress_entry import GoalProgressEntry

router = APIRouter(tags=["activity-review"])


def owned_session(db: Session, session_id: UUID, user_id: UUID, *, lock: bool = False) -> ActivitySession:
    query = select(ActivitySession).where(ActivitySession.id == session_id, ActivitySession.user_id == user_id)
    if lock:
        query = query.with_for_update()
    item = db.scalar(query)
    if item is None:
        raise HTTPException(status_code=404, detail="Activity session not found.")
    return item


def validate_associations(db: Session, payload, user_id: UUID) -> None:
    for model, field in ((ScheduleItem, "schedule_item_id"), (Task, "task_id"), (Habit, "habit_id"), (Project, "project_id"), (Target, "target_id")):
        value = getattr(payload, field, None)
        if value is None:
            continue
        query = select(model).where(model.id == value, model.user_id == user_id)
        row = db.scalar(query)
        if row is None or (model is ScheduleItem and row.deleted_at is not None) or (model is Task and row.deleted_at is not None):
            raise HTTPException(status_code=404, detail=f"{model.__name__} not found.")


@router.get("/activity-events", response_model=list[ActivityEventWithSource])
def list_observations(
    status_filter: str = Query(default="all", alias="status", pattern="^(all|unreviewed|linked|discarded)$"),
    source_id: UUID | None = None,
    event_type: str | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = (
        select(ActivityEvent, ActivitySource)
        .join(ActivitySource, (ActivitySource.id == ActivityEvent.source_id) & (ActivitySource.user_id == ActivityEvent.user_id))
        .where(ActivityEvent.user_id == user.id)
    )
    if source_id:
        query = query.where(ActivityEvent.source_id == source_id)
    if event_type:
        query = query.where(ActivityEvent.event_type == event_type)
    if start_at:
        query = query.where(ActivityEvent.occurred_at >= start_at)
    if end_at:
        query = query.where(ActivityEvent.occurred_at <= end_at)
    query = query.order_by(ActivityEvent.occurred_at.desc(), ActivityEvent.id).limit(limit)
    result = []
    for event, source in db.execute(query).all():
        session_ids = list(db.scalars(select(ActivitySessionEvent.activity_session_id).join(
            ActivitySession,
            (ActivitySession.id == ActivitySessionEvent.activity_session_id) & (ActivitySession.user_id == ActivitySessionEvent.user_id),
        ).where(ActivitySessionEvent.activity_event_id == event.id, ActivitySessionEvent.user_id == user.id)).all())
        if status_filter == "discarded" and event.discarded_at is None:
            continue
        if status_filter == "unreviewed" and (session_ids or event.discarded_at is not None):
            continue
        if status_filter == "linked" and not session_ids:
            continue
        result.append(ActivityEventWithSource(
            id=event.id, source_id=event.source_id, source_name=source.name, source_type=source.source_type,
            external_event_id=event.external_event_id, event_type=event.event_type, occurred_at=event.occurred_at,
            received_at=event.received_at, confidence=event.confidence, payload=event.payload,
            discarded_at=event.discarded_at, session_ids=session_ids,
        ))
    return result


@router.post("/activity-events/{event_id}/discard", status_code=status.HTTP_204_NO_CONTENT)
def discard_observation(event_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    event = db.scalar(select(ActivityEvent).where(ActivityEvent.id == event_id, ActivityEvent.user_id == user.id).with_for_update())
    if event is None:
        raise HTTPException(status_code=404, detail="Activity event not found.")
    linked = list(db.scalars(select(ActivitySession).join(
        ActivitySessionEvent,
        (ActivitySessionEvent.activity_session_id == ActivitySession.id) & (ActivitySessionEvent.user_id == ActivitySession.user_id),
    ).where(ActivitySessionEvent.activity_event_id == event.id, ActivitySession.user_id == user.id).with_for_update()).all())
    if any(item.status in {"confirmed", "corrected"} for item in linked):
        raise HTTPException(status_code=409, detail="Correct or discard linked sessions before discarding this observation.")
    now = datetime.now(UTC)
    event.discarded_at = event.discarded_at or now
    for item in linked:
        item.status = "discarded"
    db.commit()


@router.get("/activity-sessions", response_model=list[ActivitySessionRead])
def list_activity_sessions(
    status_filter: str | None = Query(default=None, alias="status", pattern="^(draft|confirmed|corrected|discarded|superseded)$"),
    source_kind: str | None = Query(default=None, pattern="^(observed|manual|stopwatch|merged|legacy)$"),
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = select(ActivitySession).where(ActivitySession.user_id == user.id)
    if status_filter:
        query = query.where(ActivitySession.status == status_filter)
    if source_kind:
        query = query.where(ActivitySession.source_kind == source_kind)
    if start_at:
        query = query.where(ActivitySession.started_at >= start_at)
    if end_at:
        query = query.where(ActivitySession.started_at <= end_at)
    return list(db.scalars(query.order_by(ActivitySession.started_at.desc(), ActivitySession.id).limit(limit)).all())


@router.get("/activity-sessions/{session_id}/evidence", response_model=list[ActivityEventWithSource])
def session_evidence(session_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    owned_session(db, session_id, user.id)
    rows = db.execute(
        select(ActivityEvent, ActivitySource)
        .join(ActivitySessionEvent, (ActivitySessionEvent.activity_event_id == ActivityEvent.id) & (ActivitySessionEvent.user_id == ActivityEvent.user_id))
        .join(ActivitySource, (ActivitySource.id == ActivityEvent.source_id) & (ActivitySource.user_id == ActivityEvent.user_id))
        .where(ActivitySessionEvent.activity_session_id == session_id, ActivitySessionEvent.user_id == user.id)
        .order_by(ActivityEvent.occurred_at, ActivityEvent.id)
    ).all()
    return [ActivityEventWithSource(
        id=event.id, source_id=event.source_id, source_name=source.name, source_type=source.source_type,
        external_event_id=event.external_event_id, event_type=event.event_type, occurred_at=event.occurred_at,
        received_at=event.received_at, confidence=event.confidence, payload=event.payload,
        discarded_at=event.discarded_at, session_ids=[session_id],
    ) for event, source in rows]


@router.get("/activity-sessions/{session_id}/corrections", response_model=list[ActivityCorrectionRead])
def session_corrections(session_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    owned_session(db, session_id, user.id)
    return list(db.scalars(select(ActivityCorrection).where(
        ActivityCorrection.activity_session_id == session_id, ActivityCorrection.user_id == user.id
    ).order_by(ActivityCorrection.created_at, ActivityCorrection.id)).all())


@router.get("/activity-sessions/{session_id}/contributions")
def list_contributions(session_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    owned_session(db, session_id, user.id)
    rows = db.execute(select(ActivityGoalContribution, Target.title, AmbitionGoal.title).outerjoin(
        Target, (Target.id == ActivityGoalContribution.target_id) & (Target.user_id == ActivityGoalContribution.user_id)
    ).outerjoin(AmbitionGoal, (AmbitionGoal.id == ActivityGoalContribution.goal_id) & (AmbitionGoal.user_id == ActivityGoalContribution.user_id)).where(ActivityGoalContribution.activity_session_id == session_id, ActivityGoalContribution.user_id == user.id).order_by(ActivityGoalContribution.created_at, ActivityGoalContribution.id)).all()
    return [{"id": row.id, "target_id": row.target_id, "goal_id": row.goal_id, "target_title": target_title or goal_title, "contribution_type": row.contribution_type, "contribution_value": row.contribution_value, "unit": row.unit, "details": row.details, "reversed_at": row.reversed_at} for row, target_title, goal_title in rows]


@router.post("/activity-sessions", response_model=ActivitySessionRead, status_code=status.HTTP_201_CREATED)
def create_activity_session(payload: ActivitySessionCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    validate_associations(db, payload, user.id)
    events = []
    if payload.event_ids:
        events = list(db.scalars(select(ActivityEvent).where(
            ActivityEvent.user_id == user.id, ActivityEvent.id.in_(payload.event_ids), ActivityEvent.discarded_at.is_(None)
        ).with_for_update()).all())
        if len(events) != len(set(payload.event_ids)):
            raise HTTPException(status_code=404, detail="One or more source events were not found.")
        linked_ids = set(db.scalars(select(ActivitySessionEvent.activity_event_id).join(
            ActivitySession,
            (ActivitySession.id == ActivitySessionEvent.activity_session_id) & (ActivitySession.user_id == ActivitySessionEvent.user_id),
        ).where(
            ActivitySessionEvent.user_id == user.id, ActivitySessionEvent.activity_event_id.in_(payload.event_ids),
            ActivitySession.status.not_in(("superseded", "discarded")),
        )).all())
        if linked_ids:
            raise HTTPException(status_code=409, detail="A source event is already attached to a session.")
    item = ActivitySession(
        user_id=user.id, title=payload.title.strip(), notes=payload.notes, started_at=payload.started_at,
        ended_at=payload.ended_at, duration_seconds=payload.duration_seconds,
        source_kind=payload.source_kind, status="draft" if payload.source_kind == "observed" else "confirmed",
        confidence=min((event.confidence for event in events), default=1.0),
        schedule_item_id=payload.schedule_item_id, task_id=payload.task_id, habit_id=payload.habit_id,
        project_id=payload.project_id, target_id=payload.target_id,
    )
    db.add(item)
    db.flush()
    for event in events:
        db.add(ActivitySessionEvent(activity_session_id=item.id, activity_event_id=event.id, user_id=user.id))
    db.commit()
    db.refresh(item)
    return item


@router.patch("/activity-sessions/{session_id}/associations", response_model=ActivitySessionRead)
def update_associations(session_id: UUID, payload: ActivityAssociationUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = owned_session(db, session_id, user.id, lock=True)
    if item.status in {"discarded", "superseded"}:
        raise HTTPException(status_code=409, detail="Discarded or superseded sessions cannot be re-associated.")
    validate_associations(db, payload, user.id)
    values = payload.model_dump(exclude_unset=True)
    for field, value in values.items():
        previous = getattr(item, field)
        if previous == value:
            continue
        db.add(ActivityCorrection(
            user_id=user.id, activity_session_id=item.id, field_name=field,
            previous_value=str(previous) if previous is not None else None,
            new_value=str(value) if value is not None else None,
            reason="User changed activity association.",
        ))
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    return item


@router.post("/activity-sessions/{session_id}/confirm", response_model=ActivitySessionRead)
def confirm_session(session_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = owned_session(db, session_id, user.id, lock=True)
    if item.status != "draft":
        raise HTTPException(status_code=409, detail="Only draft sessions can be confirmed.")
    if item.ended_at is None or item.duration_seconds is None:
        raise HTTPException(status_code=422, detail="A session needs a completed interval before confirmation.")
    item.status = "confirmed"
    db.add(ActivityCorrection(user_id=user.id, activity_session_id=item.id, field_name="status", previous_value="draft", new_value="confirmed", reason="User confirmed activity."))
    db.commit()
    db.refresh(item)
    return item


@router.post("/activity-sessions/{session_id}/correct", response_model=ActivitySessionRead)
def correct_session(session_id: UUID, payload: ActivitySessionCorrectionRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = owned_session(db, session_id, user.id, lock=True)
    if item.status not in {"draft", "confirmed", "corrected"}:
        raise HTTPException(status_code=409, detail="This session cannot be corrected.")
    values = payload.model_dump(exclude_unset=True)
    reason = values.pop("reason")
    proposed = {key: values.get(key, getattr(item, key)) for key in ("title", "started_at", "ended_at", "duration_seconds", "notes")}
    if proposed["ended_at"] is None or proposed["ended_at"] <= proposed["started_at"]:
        raise HTTPException(status_code=422, detail="ended_at must be after started_at.")
    if proposed["duration_seconds"] is None or proposed["duration_seconds"] > (proposed["ended_at"] - proposed["started_at"]).total_seconds():
        raise HTTPException(status_code=422, detail="Credited duration cannot exceed elapsed time.")
    allocated = db.scalar(select(func.coalesce(func.sum(ActivityGoalContribution.contribution_value), 0)).where(
        ActivityGoalContribution.activity_session_id == item.id, ActivityGoalContribution.contribution_type == "time", ActivityGoalContribution.reversed_at.is_(None)
    )) or 0
    if allocated > proposed["duration_seconds"]:
        raise HTTPException(status_code=409, detail="Corrected duration is below its existing time allocations.")
    for key, value in values.items():
        previous = getattr(item, key)
        if previous != value:
            db.add(ActivityCorrection(user_id=user.id, activity_session_id=item.id, field_name=key, previous_value=previous.isoformat() if isinstance(previous, datetime) else previous, new_value=value.isoformat() if isinstance(value, datetime) else value, reason=reason))
            setattr(item, key, value)
    previous_status = item.status
    item.status = "corrected"
    db.add(ActivityCorrection(user_id=user.id, activity_session_id=item.id, field_name="status", previous_value=previous_status, new_value="corrected", reason=reason))
    db.commit()
    db.refresh(item)
    return item


@router.post("/activity-sessions/{session_id}/discard", response_model=ActivitySessionRead)
def discard_session(session_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = owned_session(db, session_id, user.id, lock=True)
    if item.status not in {"draft", "confirmed", "corrected"}:
        raise HTTPException(status_code=409, detail="This session cannot be discarded.")
    has_contributions = db.scalar(select(ActivityGoalContribution.id).where(ActivityGoalContribution.activity_session_id == item.id, ActivityGoalContribution.reversed_at.is_(None)).limit(1))
    if has_contributions:
        raise HTTPException(status_code=409, detail="Remove or correct goal contributions before discarding this session.")
    previous = item.status
    item.status = "discarded"
    db.add(ActivityCorrection(user_id=user.id, activity_session_id=item.id, field_name="status", previous_value=previous, new_value="discarded", reason="User discarded activity."))
    db.commit()
    db.refresh(item)
    return item


@router.post("/activity-sessions/{session_id}/contributions", status_code=status.HTTP_201_CREATED)
def add_contributions(session_id: UUID, payload: ContributionSet, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = owned_session(db, session_id, user.id, lock=True)
    if item.status not in {"confirmed", "corrected"}:
        raise HTTPException(status_code=409, detail="Only confirmed sessions may contribute to goals.")
    time_total = Decimal("0")
    targets = {}
    goals = {}
    for part in payload.contributions:
        if part.target_id is not None:
            target = db.scalar(select(Target).where(Target.id == part.target_id, Target.user_id == user.id).with_for_update())
            if target is None:
                raise HTTPException(status_code=404, detail="Target not found.")
            targets[target.id] = target
            measure_type, measure_unit = target.metric_type, None
        else:
            goal = db.scalar(select(AmbitionGoal).where(AmbitionGoal.id == part.goal_id, AmbitionGoal.user_id == user.id).with_for_update())
            if goal is None:
                raise HTTPException(status_code=404, detail="Ambition goal not found.")
            if goal.status != "active":
                raise HTTPException(status_code=409, detail="Only active ambition goals may receive contributions.")
            goals[goal.id] = goal
            measure_type, measure_unit = goal.measurement_type, goal.measurement_unit
        if part.contribution_type == "time":
            if measure_type not in {"time", "seconds", "duration"} or part.unit != "seconds" or part.contribution_value <= 0 or part.contribution_value != part.contribution_value.to_integral_value():
                raise HTTPException(status_code=422, detail="Time contributions require a duration target, positive value, and seconds unit.")
            time_total += part.contribution_value
        elif part.contribution_type == "metric":
            invalid_integer_target = part.target_id is not None and part.contribution_value != part.contribution_value.to_integral_value()
            if measure_type in {"time", "seconds", "duration", "milestones_completed", "qualitative"} or not part.unit or part.unit == "seconds" or invalid_integer_target or (part.target_id is None and part.unit != measure_unit):
                raise HTTPException(status_code=422, detail="Metric contribution must use a compatible numeric goal or target unit.")
        elif ((part.target_id is not None and measure_type != "milestones_completed") or (part.goal_id is not None and measure_type != "count") or part.contribution_value not in (0, 1) or part.unit is not None):
            raise HTTPException(status_code=422, detail="Milestone contribution requires a milestone-compatible destination and value 0 or 1.")
    existing_time = db.scalar(select(func.coalesce(func.sum(ActivityGoalContribution.contribution_value), 0)).where(
        ActivityGoalContribution.activity_session_id == item.id, ActivityGoalContribution.contribution_type == "time", ActivityGoalContribution.reversed_at.is_(None)
    )) or 0
    if item.duration_seconds is None or existing_time + time_total > item.duration_seconds:
        raise HTTPException(status_code=409, detail="Total allocated time exceeds confirmed session duration.")
    created = []
    for part in payload.contributions:
        row = ActivityGoalContribution(
            id=uuid4(), user_id=user.id, activity_session_id=item.id, target_id=part.target_id, goal_id=part.goal_id,
            contribution_type=part.contribution_type, contribution_value=part.contribution_value,
            unit=part.unit, details=part.details,
        )
        db.add(row)
        created.append(row)
        if part.contribution_type in {"time", "metric", "milestone"}:
            if part.target_id is not None:
                targets[part.target_id].current_value += int(part.contribution_value)
            else:
                goal = goals[part.goal_id]
                if part.contribution_type in {"time", "metric", "milestone"}:
                    goal.current_value += part.contribution_value
                entry = GoalProgressEntry(user_id=user.id, goal_id=goal.id, numeric_delta=part.contribution_value, resulting_value=goal.current_value, unit=part.unit or goal.measurement_unit, source_kind="activity", source_contribution_id=row.id, details={"activity_session_id": str(item.id), "contribution_type": part.contribution_type})
                db.add(entry)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Contribution conflicts with an existing allocation.") from exc
    return [{"id": row.id, "target_id": row.target_id, "goal_id": row.goal_id, "contribution_type": row.contribution_type, "contribution_value": row.contribution_value, "unit": row.unit} for row in created]


@router.delete("/activity-sessions/{session_id}/contributions/{contribution_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_contribution(session_id: UUID, contribution_id: UUID, reason: str = Query(min_length=1, max_length=1000), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = owned_session(db, session_id, user.id, lock=True)
    contribution = db.scalar(select(ActivityGoalContribution).where(
        ActivityGoalContribution.id == contribution_id,
        ActivityGoalContribution.activity_session_id == item.id,
        ActivityGoalContribution.user_id == user.id,
        ActivityGoalContribution.reversed_at.is_(None),
    ).with_for_update())
    if contribution is None:
        raise HTTPException(status_code=404, detail="Contribution not found.")
    target = db.scalar(select(Target).where(Target.id == contribution.target_id, Target.user_id == user.id).with_for_update()) if contribution.target_id else None
    goal = db.scalar(select(AmbitionGoal).where(AmbitionGoal.id == contribution.goal_id, AmbitionGoal.user_id == user.id).with_for_update()) if contribution.goal_id else None
    if target is not None:
        target.current_value = max(0, target.current_value - int(contribution.contribution_value))
    if goal is not None and contribution.contribution_type in {"time", "metric", "milestone"}:
        goal.current_value = max(Decimal(0), goal.current_value - contribution.contribution_value)
        db.add(GoalProgressEntry(user_id=user.id, goal_id=goal.id, numeric_delta=-contribution.contribution_value, resulting_value=goal.current_value, unit=contribution.unit, source_kind="correction", source_contribution_id=contribution.id, reason=reason, details={"reversed_contribution_id": str(contribution.id)}))
    before = {"target_id": str(contribution.target_id) if contribution.target_id else None, "goal_id": str(contribution.goal_id) if contribution.goal_id else None, "type": contribution.contribution_type, "value": str(contribution.contribution_value), "unit": contribution.unit, "details": contribution.details}
    db.add(ActivityCorrection(user_id=user.id, activity_session_id=item.id, field_name=f"contribution:{contribution.id}", previous_value=before, new_value={"reversed": True}, reason=reason))
    contribution.reversed_at = datetime.now(UTC)
    db.commit()


@router.post("/activity-sessions/{session_id}/split", response_model=list[ActivitySessionRead])
def split_session(session_id: UUID, payload: SplitRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    parent = owned_session(db, session_id, user.id, lock=True)
    if parent.status not in {"confirmed", "corrected"} or parent.ended_at is None or parent.duration_seconds is None:
        raise HTTPException(status_code=409, detail="Only completed confirmed sessions can be split.")
    if not parent.started_at < payload.split_at < parent.ended_at:
        raise HTTPException(status_code=422, detail="split_at must fall inside the session interval.")
    contributions = list(db.scalars(select(ActivityGoalContribution).where(ActivityGoalContribution.activity_session_id == parent.id, ActivityGoalContribution.user_id == user.id, ActivityGoalContribution.reversed_at.is_(None)).with_for_update()).all())
    if any(row.contribution_type != "time" for row in contributions):
        raise HTTPException(status_code=409, detail="Split metric and milestone contributions explicitly before splitting.")
    total_wall = (parent.ended_at - parent.started_at).total_seconds()
    left_wall = (payload.split_at - parent.started_at).total_seconds()
    left_duration = int(parent.duration_seconds * left_wall / total_wall)
    right_duration = parent.duration_seconds - left_duration
    if parent.duration_seconds == int(total_wall):
        left_duration = int(left_wall)
        right_duration = parent.duration_seconds - left_duration
    left = ActivitySession(user_id=user.id, title=parent.title, notes=parent.notes, started_at=parent.started_at, ended_at=payload.split_at, duration_seconds=left_duration, confidence=parent.confidence, status=parent.status, source_kind=parent.source_kind)
    right = ActivitySession(user_id=user.id, title=parent.title, notes=parent.notes, started_at=payload.split_at, ended_at=parent.ended_at, duration_seconds=right_duration, confidence=parent.confidence, status=parent.status, source_kind=parent.source_kind)
    db.add_all([left, right])
    db.flush()
    event_ids = list(db.scalars(select(ActivitySessionEvent.activity_event_id).where(ActivitySessionEvent.activity_session_id == parent.id, ActivitySessionEvent.user_id == user.id)).all())
    for child in (left, right):
        for event_id in event_ids:
            db.add(ActivitySessionEvent(activity_session_id=child.id, activity_event_id=event_id, user_id=user.id))
    for row in contributions:
        portion_left = int(row.contribution_value * Decimal(str(left_wall)) / Decimal(str(total_wall)))
        portion_right = int(row.contribution_value) - portion_left
        if portion_left:
            db.add(ActivityGoalContribution(user_id=user.id, activity_session_id=left.id, target_id=row.target_id, goal_id=row.goal_id, contribution_type="time", contribution_value=portion_left, unit="seconds", details=row.details))
        if portion_right:
            db.add(ActivityGoalContribution(user_id=user.id, activity_session_id=right.id, target_id=row.target_id, goal_id=row.goal_id, contribution_type="time", contribution_value=portion_right, unit="seconds", details=row.details))
        db.add(ActivityCorrection(user_id=user.id, activity_session_id=parent.id, field_name=f"contribution:{row.id}", previous_value=str(row.contribution_value), new_value={"left": portion_left, "right": portion_right}, reason=payload.reason))
        row.reversed_at = datetime.now(UTC)
    previous_status = parent.status
    parent.status = "superseded"
    db.add(ActivityCorrection(user_id=user.id, activity_session_id=parent.id, field_name="status", previous_value=previous_status, new_value="superseded", reason=payload.reason))
    db.add_all([
        ActivitySessionLineage(parent_session_id=parent.id, child_session_id=left.id, user_id=user.id, operation="split"),
        ActivitySessionLineage(parent_session_id=parent.id, child_session_id=right.id, user_id=user.id, operation="split"),
    ])
    db.commit()
    db.refresh(left)
    db.refresh(right)
    return [left, right]


@router.post("/activity-sessions/{session_id}/merge", response_model=ActivitySessionRead)
def merge_session(session_id: UUID, payload: MergeRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    first = owned_session(db, session_id, user.id, lock=True)
    second = owned_session(db, payload.other_session_id, user.id, lock=True)
    if first.id == second.id:
        raise HTTPException(status_code=422, detail="A session cannot be merged with itself.")
    if first.status not in {"confirmed", "corrected"} or second.status not in {"confirmed", "corrected"} or first.ended_at is None or second.ended_at is None:
        raise HTTPException(status_code=409, detail="Only completed confirmed sessions can be merged.")
    if max(first.started_at, second.started_at) < min(first.ended_at, second.ended_at):
        raise HTTPException(status_code=409, detail="Overlapping sessions cannot be merged without correcting their intervals first.")
    source_sessions = [first, second]
    start_at, end_at = min(first.started_at, second.started_at), max(first.ended_at, second.ended_at)
    total_duration = (first.duration_seconds or 0) + (second.duration_seconds or 0)
    if total_duration > (end_at - start_at).total_seconds():
        raise HTTPException(status_code=409, detail="Merged credited duration would exceed the combined interval.")
    result = ActivitySession(user_id=user.id, title=payload.title or first.title, notes="\n".join(x.notes for x in source_sessions if x.notes) or None, started_at=start_at, ended_at=end_at, duration_seconds=total_duration, confidence=min(first.confidence, second.confidence), status="corrected" if "corrected" in {first.status, second.status} else "confirmed", source_kind="merged")
    db.add(result)
    db.flush()
    all_events = set()
    contributions = []
    for source in source_sessions:
        all_events.update(db.scalars(select(ActivitySessionEvent.activity_event_id).where(ActivitySessionEvent.activity_session_id == source.id, ActivitySessionEvent.user_id == user.id)).all())
        contributions.extend(db.scalars(select(ActivityGoalContribution).where(ActivityGoalContribution.activity_session_id == source.id, ActivityGoalContribution.user_id == user.id, ActivityGoalContribution.reversed_at.is_(None)).with_for_update()).all())
    for event_id in all_events:
        db.add(ActivitySessionEvent(activity_session_id=result.id, activity_event_id=event_id, user_id=user.id))
    time_totals = {}
    for row in contributions:
        if row.contribution_type == "time":
            destination = (row.target_id, row.goal_id)
            time_totals[destination] = time_totals.get(destination, 0) + int(row.contribution_value)
        else:
            db.add(ActivityGoalContribution(user_id=user.id, activity_session_id=result.id, target_id=row.target_id, goal_id=row.goal_id, contribution_type=row.contribution_type, contribution_value=row.contribution_value, unit=row.unit, details=row.details))
        db.add(ActivityCorrection(user_id=user.id, activity_session_id=row.activity_session_id, field_name=f"contribution:{row.id}", previous_value=str(row.contribution_value), new_value={"merged_session": str(result.id)}, reason=payload.reason))
        row.reversed_at = datetime.now(UTC)
    for (target_id, goal_id), seconds in time_totals.items():
        db.add(ActivityGoalContribution(user_id=user.id, activity_session_id=result.id, target_id=target_id, goal_id=goal_id, contribution_type="time", contribution_value=seconds, unit="seconds"))
    for source in source_sessions:
        old = source.status
        source.status = "superseded"
        db.add(ActivityCorrection(user_id=user.id, activity_session_id=source.id, field_name="status", previous_value=old, new_value="superseded", reason=payload.reason))
        db.add(ActivitySessionLineage(parent_session_id=source.id, child_session_id=result.id, user_id=user.id, operation="merge"))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Merged contributions violate the target allocation limit.") from exc
    db.refresh(result)
    return result

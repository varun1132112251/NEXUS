from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import get_current_user
from app.db.session import get_db
from app.models.habit import Habit
from app.models.project import Project
from app.models.schedule import ScheduleItem
from app.models.task import Task
from app.models.target import Target
from app.models.routine_template import RoutineTemplate
from app.models.ambition_goal import AmbitionGoal
from app.models.activity_session import ActivitySession
from app.models.time_session import TimeSession
from app.models.time_session_segment import TimeSessionSegment
from app.models.user import User
from app.schemas.schedule import ScheduleItemCreate, ScheduleItemRead, ScheduleItemUpdate, ScheduleStatusEventRead
from app.schemas.analytics import ScheduleExecutionSummary, ScheduleExecutionItem, ScheduleExecutionTotals
from app.models.schedule_status_event import ScheduleStatusEvent
from app.services.planner import (
    lock_user_schedule, normalize_planner_interval, reject_schedule_conflict,
    schedule_conflicts, user_timezone,
)

router = APIRouter(prefix="/schedule", tags=["schedule"])


def union_seconds(intervals: list[tuple[datetime, datetime]]) -> int:
    if not intervals:
        return 0
    merged: list[list[datetime]] = []
    for start_at, end_at in sorted(intervals):
        if not merged or start_at > merged[-1][1]:
            merged.append([start_at, end_at])
        elif end_at > merged[-1][1]:
            merged[-1][1] = end_at
    return sum(max(0, int((end - start).total_seconds())) for start, end in merged)


def subtract_intervals(intervals: list[tuple[datetime, datetime]], excluded: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    result = []
    for start_at, end_at in intervals:
        pieces = [(start_at, end_at)]
        for cut_start, cut_end in excluded:
            next_pieces = []
            for left, right in pieces:
                if cut_end <= left or cut_start >= right:
                    next_pieces.append((left, right))
                else:
                    if left < cut_start:
                        next_pieces.append((left, cut_start))
                    if cut_end < right:
                        next_pieces.append((cut_end, right))
            pieces = next_pieces
        result.extend(pieces)
    return result


@router.get("/execution", response_model=ScheduleExecutionSummary)
def execution_summary(
    start_date: date,
    end_date: date,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if end_date < start_date or end_date > start_date + timedelta(days=30):
        raise HTTPException(422, "Provide a valid range of at most 31 days.")
    blocks = list(db.scalars(select(ScheduleItem).where(
        ScheduleItem.user_id == user.id, ScheduleItem.deleted_at.is_(None),
        ScheduleItem.scheduled_date >= start_date, ScheduleItem.scheduled_date <= end_date,
    ).order_by(ScheduleItem.scheduled_date, ScheduleItem.start_at)).all())
    block_by_id = {block.id: block for block in blocks}
    block_ids = list(block_by_id)
    timezone = user_timezone(db, user.id)
    range_start = datetime.combine(start_date, datetime.min.time(), timezone).astimezone(UTC)
    range_end = datetime.combine(end_date + timedelta(days=1), datetime.min.time(), timezone).astimezone(UTC)
    rows = db.execute(select(ActivitySession, TimeSession.schedule_item_id).outerjoin(
        TimeSession, and_(TimeSession.id == ActivitySession.time_session_id, TimeSession.user_id == ActivitySession.user_id)
    ).where(
        ActivitySession.user_id == user.id,
        ActivitySession.status.in_(("confirmed", "corrected")),
        ActivitySession.ended_at.is_not(None),
        ActivitySession.started_at < range_end,
        ActivitySession.ended_at > range_start,
    )).all()
    timer_ids = {activity.time_session_id for activity, _ in rows if activity.time_session_id is not None}
    segment_rows = list(db.scalars(select(TimeSessionSegment).where(
        TimeSessionSegment.user_id == user.id,
        TimeSessionSegment.time_session_id.in_(timer_ids),
        TimeSessionSegment.ended_at.is_not(None),
    ).order_by(TimeSessionSegment.started_at, TimeSessionSegment.id)).all()) if timer_ids else []
    segments_by_timer: dict[UUID, list[tuple[datetime, datetime]]] = {}
    for segment in segment_rows:
        if segment.ended_at > segment.started_at:
            segments_by_timer.setdefault(segment.time_session_id, []).append((segment.started_at, segment.ended_at))
    linked: dict[UUID, list[tuple[datetime, datetime]]] = {block_id: [] for block_id in block_ids}
    linked_counts: dict[UUID, int] = {block_id: 0 for block_id in block_ids}
    unavailable_by_block: dict[UUID, int] = {block_id: 0 for block_id in block_ids}
    unavailable_legacy_seconds = 0
    all_intervals: list[tuple[datetime, datetime]] = []
    unlinked_intervals: list[tuple[datetime, datetime]] = []
    annotated_intervals: list[tuple[datetime, datetime, UUID | None]] = []
    for activity, timer_schedule_id in rows:
        intervals = []
        if activity.time_session_id is not None:
            intervals = segments_by_timer.get(activity.time_session_id, [])
            if not intervals and activity.duration_seconds:
                unavailable_legacy_seconds += activity.duration_seconds
        elif activity.duration_seconds:
            intervals = [(activity.started_at, activity.started_at + timedelta(seconds=activity.duration_seconds))]
        intervals = [
            (max(left, range_start), min(right, range_end))
            for left, right in intervals
            if min(right, range_end) > max(left, range_start)
        ]
        all_intervals.extend(intervals)
        schedule_id = activity.schedule_item_id or timer_schedule_id
        if schedule_id in linked:
            linked[schedule_id].extend(intervals)
            linked_counts[schedule_id] += 1
            if activity.time_session_id is not None and not intervals and activity.duration_seconds:
                unavailable_by_block[schedule_id] += activity.duration_seconds
            annotated_intervals.extend((left, right, schedule_id) for left, right in intervals)
        else:
            unlinked_intervals.extend(intervals)
            annotated_intervals.extend((left, right, None) for left, right in intervals)

    results = []
    associated_by_block = {}
    for block in blocks:
        planned = max(0, int((block.end_at - block.start_at).total_seconds())) if block.status != "cancelled" else 0
        inside = []
        outside = []
        for left, right in linked[block.id]:
            clipped_left, clipped_right = max(left, block.start_at), min(right, block.end_at)
            if clipped_right > clipped_left:
                inside.append((clipped_left, clipped_right))
            if left < block.start_at:
                outside.append((left, min(right, block.start_at)))
            if right > block.end_at:
                outside.append((max(left, block.end_at), right))
        associated_by_block[block.id] = inside
        ambiguous = [
            (max(left, block.start_at), min(right, block.end_at))
            for left, right in unlinked_intervals
            if min(right, block.end_at) > max(left, block.start_at)
        ]
        results.append(ScheduleExecutionItem(
            schedule_item=block,
            planned_seconds=planned,
            confirmed_actual_seconds=union_seconds(inside),
            outside_planned_seconds=union_seconds(outside),
            ambiguous_actual_seconds=union_seconds(ambiguous),
            unavailable_legacy_seconds=unavailable_by_block[block.id],
            confirmed_session_count=linked_counts[block.id],
        ))

    planned_blocks = [block for block in blocks if block.status != "cancelled"]
    associated_union, ambiguous_union, outside_union = [], [], []
    points = sorted({point for left, right, _ in annotated_intervals for point in (left, right)} |
                    {point for block in planned_blocks for point in (block.start_at, block.end_at)})
    for left, right in zip(points, points[1:]):
        if right <= left:
            continue
        active_links = {schedule_id for start_at, end_at, schedule_id in annotated_intervals if start_at < right and end_at > left}
        if not active_links:
            continue
        active_links.discard(None)
        matching_blocks = [block for block in planned_blocks if block.start_at < right and block.end_at > left]
        seconds_interval = (left, right)
        if len(active_links) > 1 or (None in {schedule_id for start_at, end_at, schedule_id in annotated_intervals if start_at < right and end_at > left} and matching_blocks):
            ambiguous_union.append(seconds_interval)
        elif len(active_links) == 1:
            block_id = next(iter(active_links))
            block = block_by_id.get(block_id)
            if block and block.start_at <= left and right <= block.end_at:
                associated_union.append(seconds_interval)
            else:
                outside_union.append(seconds_interval)
        elif matching_blocks:
            ambiguous_union.append(seconds_interval)
        else:
            outside_union.append(seconds_interval)
    for result in results:
        block = result.schedule_item
        ambiguous_for_block = [
            (max(left, block.start_at), min(right, block.end_at))
            for left, right in ambiguous_union
            if min(right, block.end_at) > max(left, block.start_at)
        ]
        exclusive = subtract_intervals(associated_by_block[block.id], ambiguous_for_block)
        result.confirmed_actual_seconds = union_seconds(exclusive)
        result.ambiguous_actual_seconds = union_seconds(ambiguous_for_block)
    status_counts = {name: sum(block.status == name for block in blocks) for name in ("completed", "partial", "missed", "skipped", "cancelled")}
    planned_count = len(planned_blocks)
    completed_count = status_counts["completed"]
    return ScheduleExecutionSummary(
        items=results,
        totals=ScheduleExecutionTotals(
            planned_seconds=sum(item.planned_seconds for item in results),
            confirmed_actual_seconds=union_seconds(all_intervals),
            associated_actual_seconds=union_seconds(associated_union),
            outside_planned_seconds=union_seconds(outside_union),
            ambiguous_actual_seconds=union_seconds(ambiguous_union),
            unavailable_legacy_seconds=unavailable_legacy_seconds,
            planned_items=planned_count,
            completed_items=completed_count,
            partial_items=status_counts["partial"], missed_items=status_counts["missed"],
            skipped_items=status_counts["skipped"], cancelled_items=status_counts["cancelled"],
            completion_rate=round(completed_count / planned_count * 100, 2) if planned_count else 0.0,
        ),
    )

SCHEDULE_TRANSITIONS = {
    "planned": {"partial", "completed", "skipped", "missed", "cancelled"},
    "partial": {"planned", "completed", "skipped", "missed", "cancelled"},
    "completed": {"planned"},
    "skipped": {"planned"},
    "missed": {"planned"},
    "cancelled": {"planned"},
}


def owned(db: Session, model, item_id: UUID, user_id: UUID, *, include_deleted: bool = False):
    query = select(model).where(model.id == item_id, model.user_id == user_id).with_for_update()
    if model is ScheduleItem and not include_deleted:
        query = query.where(ScheduleItem.deleted_at.is_(None))
    item = db.scalar(query)
    if item is None:
        raise HTTPException(status_code=404, detail=f"{model.__name__} not found.")
    return item


def validate_links(db: Session, payload, user_id: UUID):
    if payload.task_id is not None:
        owned(db, Task, payload.task_id, user_id)
    if payload.habit_id is not None:
        owned(db, Habit, payload.habit_id, user_id)
    if payload.project_id is not None:
        owned(db, Project, payload.project_id, user_id)
    if payload.target_id is not None:
        owned(db, Target, payload.target_id, user_id)
    if payload.routine_template_id is not None:
        routine = owned(db, RoutineTemplate, payload.routine_template_id, user_id)
        if not routine.active:
            raise HTTPException(status_code=409, detail="Inactive routine templates cannot be linked to new schedule blocks.")
    if payload.ambition_goal_id is not None:
        owned(db, AmbitionGoal, payload.ambition_goal_id, user_id)


@router.post("", response_model=ScheduleItemRead, status_code=status.HTTP_201_CREATED)
def create(
    payload: ScheduleItemCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    allow_conflict: bool = False,
):
    lock_user_schedule(db, user.id)
    timezone = user_timezone(db, user.id)
    start_at, end_at = normalize_planner_interval(payload.start_at, payload.end_at, payload.scheduled_date, timezone)
    validate_links(db, payload, user.id)
    conflicts = schedule_conflicts(db, user_id=user.id, start_at=start_at, end_at=end_at)
    reject_schedule_conflict(conflicts, allow_conflict)
    item = ScheduleItem(user_id=user.id, **payload.model_dump(exclude={"start_at", "end_at"}), start_at=start_at, end_at=end_at)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("", response_model=list[ScheduleItemRead])
def list_schedule(
    scheduled_date: date | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    include_deleted: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = select(ScheduleItem).where(ScheduleItem.user_id == user.id)
    if (start_date is None) != (end_date is None):
        raise HTTPException(422, "start_date and end_date must be provided together.")
    if start_date is not None and end_date is not None:
        if end_date < start_date:
            raise HTTPException(422, "end_date must be on or after start_date.")
        if end_date > start_date + timedelta(days=30):
            raise HTTPException(422, "Schedule range cannot exceed 31 days.")
        query = query.where(ScheduleItem.scheduled_date >= start_date, ScheduleItem.scheduled_date <= end_date)
    if not include_deleted:
        query = query.where(ScheduleItem.deleted_at.is_(None))
    if scheduled_date is not None:
        if start_date is not None:
            raise HTTPException(422, "Use scheduled_date or a date range, not both.")
        query = query.where(ScheduleItem.scheduled_date == scheduled_date)
    query = query.order_by(ScheduleItem.scheduled_date, ScheduleItem.start_at)
    return list(db.scalars(query).all())


@router.patch("/{schedule_id}", response_model=ScheduleItemRead)
def update(
    schedule_id: UUID,
    payload: ScheduleItemUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    allow_conflict: bool = False,
):
    lock_user_schedule(db, user.id)
    item = owned(db, ScheduleItem, schedule_id, user.id)
    validate_links(db, payload, user.id)
    timezone = user_timezone(db, user.id)
    values = payload.model_dump(exclude_unset=True)
    next_date = values.get("scheduled_date", item.scheduled_date)
    if "scheduled_date" in values and "start_at" not in values and "end_at" not in values:
        local_start = item.start_at.astimezone(timezone).replace(tzinfo=None)
        local_end = item.end_at.astimezone(timezone).replace(tzinfo=None)
        requested_start = datetime.combine(next_date, local_start.time())
        requested_end = datetime.combine(next_date, local_end.time())
    else:
        requested_start = values.get("start_at", item.start_at)
        requested_end = values.get("end_at", item.end_at)
    start_at, end_at = normalize_planner_interval(requested_start, requested_end, next_date, timezone)
    next_status = values.get("status")
    if next_status is not None and next_status != item.status and next_status not in SCHEDULE_TRANSITIONS[item.status]:
        raise HTTPException(409, f"Schedule block cannot transition from {item.status} to {next_status}.")
    interval_changed = start_at != item.start_at or end_at != item.end_at or next_date != item.scheduled_date
    if interval_changed:
        conflicts = schedule_conflicts(db, user_id=user.id, start_at=start_at, end_at=end_at, exclude_id=item.id)
        reject_schedule_conflict(conflicts, allow_conflict)
    for key, value in values.items():
        if key not in {"start_at", "end_at", "scheduled_date"}:
            setattr(item, key, value)
    item.scheduled_date = next_date
    item.start_at = start_at
    item.end_at = end_at

    db.commit()
    db.refresh(item)
    return item


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(
    schedule_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = owned(db, ScheduleItem, schedule_id, user.id)
    # Hide the planned block while preserving stopwatch/activity associations.
    item.deleted_at = datetime.now(UTC)
    db.commit()


@router.get("/{schedule_id}/history", response_model=list[ScheduleStatusEventRead])
def status_history(schedule_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    owned(db, ScheduleItem, schedule_id, user.id, include_deleted=True)
    return list(db.scalars(select(ScheduleStatusEvent).where(
        ScheduleStatusEvent.schedule_item_id == schedule_id,
        ScheduleStatusEvent.user_id == user.id,
    ).order_by(ScheduleStatusEvent.created_at, ScheduleStatusEvent.id)).all())

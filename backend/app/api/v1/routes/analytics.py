from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
import re

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import get_current_user
from app.db.session import get_db
from app.models.activity_record import ActivityRecord
from app.models.diary import DiaryEntry
from app.models.schedule import ScheduleItem
from app.models.target import Target
from app.models.activity_session import ActivitySession
from app.models.activity_goal_contribution import ActivityGoalContribution
from app.models.time_session_segment import TimeSessionSegment
from app.models.user import User
from app.schemas.analytics import (
    ActivityBreakdown,
    AnalyticsDay,
    AnalyticsSummary,
    AnalyticsTotals,
    ReflectionSummary,
    TargetProgress,
)
from app.services.planner import user_timezone

router = APIRouter(prefix="/analytics", tags=["analytics"])


def local_day(dt: datetime, timezone) -> date:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(timezone).date()


def seconds_between(start: datetime, end: datetime) -> int:
    return max(0, int((end - start).total_seconds()))


def union_seconds(intervals: list[tuple[datetime, datetime]]) -> int:
    merged: list[list[datetime]] = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        elif end > merged[-1][1]:
            merged[-1][1] = end
    return sum(seconds_between(start, end) for start, end in merged)


def canonical_label(value: str | None) -> tuple[str, str]:
    label = re.sub(r"\s+", " ", (value or "Unlinked").strip())
    return label, label.casefold()


@router.get("/summary", response_model=AnalyticsSummary)
def summary(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AnalyticsSummary:
    timezone = user_timezone(db, user.id)
    today = datetime.now(timezone).date()
    start = start_date or today
    end = end_date or start
    if end < start:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="end_date must be on or after start_date.")
    if (end - start).days > 365:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="Analytics range cannot exceed 366 calendar days.")

    schedules = list(db.scalars(select(ScheduleItem).where(
        ScheduleItem.user_id == user.id,
        ScheduleItem.deleted_at.is_(None),
        ScheduleItem.scheduled_date >= start,
        ScheduleItem.scheduled_date <= end,
    )).all())

    range_start = datetime.combine(start, time.min, timezone).astimezone(UTC)
    range_end = datetime.combine(end + timedelta(days=1), time.min, timezone).astimezone(UTC)

    sessions = list(db.scalars(select(ActivitySession).where(
        ActivitySession.user_id == user.id,
        ActivitySession.status.in_(("confirmed", "corrected")),
        ActivitySession.started_at < range_end,
        ActivitySession.ended_at.is_not(None),
        ActivitySession.ended_at >= range_start,
    )).all())

    activities = list(db.scalars(select(ActivityRecord).where(
        ActivityRecord.user_id == user.id,
        ActivityRecord.recorded_at >= range_start,
        ActivityRecord.recorded_at < range_end,
    )).all())

    diaries = list(db.scalars(select(DiaryEntry).where(
        DiaryEntry.user_id == user.id,
        DiaryEntry.entry_date >= start,
        DiaryEntry.entry_date <= end,
    )).all())

    days = [start.fromordinal(n) for n in range(start.toordinal(), end.toordinal() + 1)]
    planned_by_day = {day: 0 for day in days}
    actual_by_day = {day: 0 for day in days}
    planned_items_by_day = {day: 0 for day in days}
    completed_items_by_day = {day: 0 for day in days}
    activity_by_day = {day: 0 for day in days}
    draft_by_day = {day: 0 for day in days}

    for item in schedules:
        day = item.scheduled_date
        if item.status != "cancelled":
            planned_by_day[day] += seconds_between(item.start_at, item.end_at)
            planned_items_by_day[day] += 1
        if item.status == "completed":
            completed_items_by_day[day] += 1

    actual_intervals: dict[date, list[tuple[datetime, datetime]]] = {day: [] for day in days}
    category_intervals = defaultdict(list)
    session_actual_intervals: dict[object, list[tuple[datetime, datetime]]] = defaultdict(list)
    unavailable_legacy_seconds = 0
    for session in sessions:
        intervals: list[tuple[datetime, datetime]] = []
        if session.time_session_id is not None:
            segments = db.scalars(select(TimeSessionSegment).where(
                TimeSessionSegment.time_session_id == session.time_session_id,
                TimeSessionSegment.user_id == user.id,
                TimeSessionSegment.ended_at.is_not(None),
            )).all()
            intervals.extend((segment.started_at, segment.ended_at) for segment in segments if segment.ended_at > segment.started_at)
            if not intervals and session.duration_seconds:
                # No pause history exists for this legacy timer. Do not synthesize a segment.
                unavailable_legacy_seconds += session.duration_seconds
        elif session.duration_seconds and session.duration_seconds > 0:
            intervals.append((session.started_at, session.started_at + timedelta(seconds=session.duration_seconds)))
        for interval_start, interval_end in intervals:
            session_actual_intervals[session.id].append((interval_start, interval_end))
            cursor = max(interval_start, range_start)
            clipped_end = min(interval_end, range_end)
            while cursor < clipped_end:
                day = local_day(cursor, timezone)
                next_midnight = datetime.combine(day + timedelta(days=1), time.min, timezone).astimezone(UTC)
                part_end = min(clipped_end, next_midnight)
                if day in actual_intervals:
                    actual_intervals[day].append((cursor, part_end))
                    label, normalized_key = canonical_label(session.title)
                    category_key = f"activity_session:{session.source_kind}:{normalized_key}"
                    category_intervals[category_key].append((cursor, part_end))
                cursor = part_end
    for day in days:
        actual_by_day[day] = union_seconds(actual_intervals[day])

    for activity in activities:
        day = local_day(activity.recorded_at, timezone)
        if day in activity_by_day:
            activity_by_day[day] += 1

    planned_items = sum(1 for item in schedules if item.status != "cancelled")
    completed_items = sum(completed_items_by_day.values())
    skipped_items = sum(1 for item in schedules if item.status == "skipped")
    partial_items = sum(1 for item in schedules if item.status == "partial")
    missed_items = sum(1 for item in schedules if item.status == "missed")
    cancelled_items = sum(1 for item in schedules if item.status == "cancelled")
    planned_seconds = sum(planned_by_day.values())
    actual_seconds = sum(actual_by_day.values())
    schedule_rate = round((completed_items / planned_items) * 100, 2) if planned_items else 0.0
    time_rate = round((actual_seconds / planned_seconds) * 100, 2) if planned_seconds else 0.0

    targets = list(db.scalars(select(Target).where(
        Target.user_id == user.id,
        Target.month >= start.replace(day=1),
        Target.month <= end.replace(day=1),
    ).order_by(Target.month, Target.created_at)).all())

    breakdown_map = defaultdict(lambda: {"label": "", "seconds": 0, "ambiguous_seconds": 0, "session_count": 0, "activity_count": 0, "metric_total": 0, "source_kind": "activity_session"})
    for session in sessions:
        label, key = canonical_label(session.title)
        key = f"activity_session:{session.source_kind}:{key}"
        bucket = breakdown_map[key]
        bucket["label"] = bucket["label"] or label
        bucket["session_count"] += 1
        bucket["source_kind"] = f"activity_session:{session.source_kind}"
    # Attribute only intervals covered by a single distinct activity label.
    points = sorted({point for intervals in category_intervals.values() for interval in intervals for point in interval})
    for left, right in zip(points, points[1:]):
        if right <= left:
            continue
        active_keys = [key for key, intervals in category_intervals.items() if any(start_at < right and end_at > left for start_at, end_at in intervals)]
        seconds = seconds_between(left, right)
        if len(active_keys) == 1:
            breakdown_map[active_keys[0]]["seconds"] += seconds
        elif len(active_keys) > 1:
            for key in active_keys:
                breakdown_map[key]["ambiguous_seconds"] += seconds
    for activity in activities:
        label, normalized_key = canonical_label(activity.title)
        key = f"activity_record:{normalized_key}"
        bucket = breakdown_map[key]
        bucket["label"] = bucket["label"] or label
        bucket["activity_count"] += 1
        bucket["metric_total"] += activity.metric_value or 0
        bucket["source_kind"] = "activity_record"

    allocation_rows = db.execute(select(
        ActivityGoalContribution.activity_session_id,
        func.sum(ActivityGoalContribution.contribution_value),
    ).where(
        ActivityGoalContribution.user_id == user.id,
        ActivityGoalContribution.activity_session_id.in_([session.id for session in sessions]),
        ActivityGoalContribution.contribution_type == "time",
        ActivityGoalContribution.reversed_at.is_(None),
    ).group_by(ActivityGoalContribution.activity_session_id)).all() if sessions else []
    claims = {session_id: int(value) for session_id, value in allocation_rows}
    uncertain_claims = set()
    for session_id in claims:
        intervals = session_actual_intervals.get(session_id, [])
        if not intervals or any(left < range_start or right > range_end for left, right in intervals):
            uncertain_claims.add(session_id)
            continue
        if any(
            left < other_right and right > other_left
            for other_id, other_intervals in session_actual_intervals.items()
            if other_id != session_id
            for left, right in intervals
            for other_left, other_right in other_intervals
        ):
            uncertain_claims.add(session_id)
    allocated_seconds = sum(value for session_id, value in claims.items() if session_id not in uncertain_claims)
    allocation_attribution_unavailable = sum(claims[session_id] for session_id in uncertain_claims)
    all_allocation_claims = sum(claims.values())
    allocation_overlap_excess = max(0, all_allocation_claims - actual_seconds)
    unallocated_seconds = (
        max(0, actual_seconds - allocated_seconds)
        if allocation_attribution_unavailable == 0 and allocation_overlap_excess == 0
        else None
    )

    drafts = list(db.scalars(select(ActivitySession).where(
        ActivitySession.user_id == user.id,
        ActivitySession.status == "draft",
        ActivitySession.started_at < range_end,
        ActivitySession.ended_at.is_not(None),
        ActivitySession.ended_at >= range_start,
    )).all())
    draft_intervals_by_day = {day: [] for day in days}
    for session in drafts:
        if session.time_session_id is not None:
            segments = db.scalars(select(TimeSessionSegment).where(
                TimeSessionSegment.time_session_id == session.time_session_id,
                TimeSessionSegment.user_id == user.id,
                TimeSessionSegment.ended_at.is_not(None),
            )).all()
            draft_intervals = [(row.started_at, row.ended_at) for row in segments if row.ended_at > row.started_at]
        elif session.duration_seconds:
            draft_intervals = [(session.started_at, session.started_at + timedelta(seconds=session.duration_seconds))]
        else:
            draft_intervals = []
        for interval_start, interval_end in draft_intervals:
            cursor = max(interval_start, range_start)
            clipped_end = min(interval_end, range_end)
            while cursor < clipped_end:
                day = local_day(cursor, timezone)
                next_midnight = datetime.combine(day + timedelta(days=1), time.min, timezone).astimezone(UTC)
                part_end = min(clipped_end, next_midnight)
                if day in draft_intervals_by_day:
                    draft_intervals_by_day[day].append((cursor, part_end))
                cursor = part_end
    for day, intervals in draft_intervals_by_day.items():
        draft_by_day[day] = union_seconds(intervals)

    target_progress = []
    for target in targets:
        percent = None
        if target.target_value is not None and target.target_value > 0:
            percent = round(min(100.0, (target.current_value / target.target_value) * 100), 2)
        target_progress.append(TargetProgress(
            id=str(target.id),
            title=target.title,
            month=target.month,
            target_value=target.target_value,
            current_value=target.current_value,
            progress_percent=percent,
            status=target.status,
        ))

    reflection = ReflectionSummary(
        days_with_entries=len(diaries),
        days_with_accomplishments=sum(bool(x.accomplishments and x.accomplishments.strip()) for x in diaries),
        days_with_learning=sum(bool(x.learned and x.learned.strip()) for x in diaries),
        days_with_tomorrow_changes=sum(bool(x.tomorrow_changes and x.tomorrow_changes.strip()) for x in diaries),
        days_with_distractions=sum(bool(x.distractions and x.distractions.strip()) for x in diaries),
        coverage_percent=round((len(diaries) / len(days)) * 100, 2) if days else 0.0,
    )

    breakdown = [
        ActivityBreakdown(
            key=key,
            label=value["label"] or key,
            seconds=value["seconds"],
            session_count=value["session_count"],
            activity_count=value["activity_count"],
            metric_total=value["metric_total"],
            source_kind=value["source_kind"],
            ambiguous_seconds=value["ambiguous_seconds"],
        )
        for key, value in sorted(breakdown_map.items(), key=lambda item: item[1]["seconds"], reverse=True)
    ]

    # This endpoint reports measurements only; recommendations are intentionally omitted.
    insights: list[str] = []

    return AnalyticsSummary(
        start_date=start,
        end_date=end,
        totals=AnalyticsTotals(
            planned_seconds=planned_seconds,
            actual_seconds=actual_seconds,
            planned_items=planned_items,
            completed_items=completed_items,
            skipped_items=skipped_items,
            partial_items=partial_items,
            missed_items=missed_items,
            cancelled_items=cancelled_items,
            draft_seconds=sum(draft_by_day.values()),
            allocated_seconds=allocated_seconds,
            unallocated_seconds=unallocated_seconds,
            unavailable_legacy_seconds=unavailable_legacy_seconds,
            allocation_overlap_excess_seconds=allocation_overlap_excess,
            allocation_attribution_unavailable_seconds=allocation_attribution_unavailable,
            schedule_completion_rate=schedule_rate,
            time_execution_rate=time_rate,
            session_count=len(sessions),
            activity_count=len(activities),
            diary_days=len(diaries),
        ),
        daily=[
            AnalyticsDay(
                date=day,
                planned_seconds=planned_by_day[day],
                actual_seconds=actual_by_day[day],
                planned_items=planned_items_by_day[day],
                completed_items=completed_items_by_day[day],
                activity_count=activity_by_day[day],
                draft_seconds=draft_by_day[day],
            )
            for day in days
        ],
        target_progress=target_progress,
        breakdown=breakdown,
        reflection=reflection,
        insights=insights,
    )

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import get_current_user
from app.db.session import get_db
from app.models.activity_record import ActivityRecord
from app.models.activity_correction import ActivityCorrection
from app.models.activity_event import ActivityEvent
from app.models.activity_session_event import ActivitySessionEvent
from app.models.diary import DiaryEntry
from app.models.schedule import ScheduleItem
from app.models.schedule_status_event import ScheduleStatusEvent
from app.models.target import Target
from app.models.activity_session import ActivitySession
from app.models.activity_goal_contribution import ActivityGoalContribution
from app.models.time_session_segment import TimeSessionSegment
from app.models.task import Task
from app.models.task_status_event import TaskStatusEvent
from app.models.ambition import Ambition
from app.models.ambition_goal import AmbitionGoal
from app.models.goal_progress_entry import GoalProgressEntry
from app.models.ambition_milestone import AmbitionMilestone
from app.models.ambition_lifecycle_event import AmbitionLifecycleEvent
from app.models.user import User
from app.api.v1.routes.schedules import execution_summary as schedule_execution_summary
from app.schemas.analytics import (
    ActivityBreakdown,
    AnalyticsDay,
    AnalyticsSummary,
    AnalyticsTotals,
    ReflectionSummary,
    TargetProgress,
    DailyActivity,
    DailyActivityCorrection,
    DailyDataQuality,
    DailyGoalContribution,
    DailyGoalProgress,
    DailyHistoricalActivity,
    DailyPlannedSummary,
    DailyActualSummary,
    DailyReflection,
    DailyReport,
    DailyStatusChange,
    DailyTask,
    PeriodReport,
    PeriodComparisonMetric,
    HistoricalProgressItem,
    HistoricalMilestone,
    GoalHistoryRead,
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


def _clip_intervals(intervals, start: datetime, end: datetime):
    return [(max(left, start), min(right, end)) for left, right in intervals if left < end and right > start]


def _overlap_seconds(left_intervals, right_intervals) -> int:
    intersections = []
    for left, right in left_intervals:
        for other_left, other_right in right_intervals:
            begin, finish = max(left, other_left), min(right, other_right)
            if begin < finish:
                intersections.append((begin, finish))
    return union_seconds(intersections)


def _multi_session_overlap_seconds(intervals_by_id) -> int:
    points = sorted({point for intervals in intervals_by_id.values() for interval in intervals for point in interval})
    total = 0
    for left, right in zip(points, points[1:]):
        if right <= left:
            continue
        active = sum(any(begin < right and finish > left for begin, finish in intervals) for intervals in intervals_by_id.values())
        if active > 1:
            total += seconds_between(left, right)
    return total


@router.get("/daily-report", response_model=DailyReport)
def daily_report(
    report_date: date = Query(alias="date"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DailyReport:
    """Return one profile-local day without changing the meaning of source records."""
    timezone = user_timezone(db, user.id)
    try:
        range_start = datetime.combine(report_date, time.min, timezone).astimezone(UTC)
        range_end = datetime.combine(report_date + timedelta(days=1), time.min, timezone).astimezone(UTC)
    except (OverflowError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="date is outside the supported timezone range.") from exc

    schedules = list(db.scalars(select(ScheduleItem).where(
        ScheduleItem.user_id == user.id,
        ScheduleItem.deleted_at.is_(None),
        ScheduleItem.scheduled_date == report_date,
    ).order_by(ScheduleItem.start_at, ScheduleItem.id)).all())
    scheduled_task_ids = {item.task_id for item in schedules if item.task_id is not None and item.status != "cancelled"}
    task_date_filter = (Task.due_at >= range_start) & (Task.due_at < range_end)
    task_relevance = or_(task_date_filter, Task.id.in_(scheduled_task_ids)) if scheduled_task_ids else task_date_filter
    tasks = list(db.scalars(select(Task).where(
        Task.user_id == user.id,
        Task.deleted_at.is_(None),
        task_relevance,
    ).order_by(Task.due_at, Task.priority, Task.id)).all())

    session_rows = list(db.scalars(select(ActivitySession).where(
        ActivitySession.user_id == user.id,
        ActivitySession.started_at < range_end,
        (ActivitySession.ended_at.is_(None) | (ActivitySession.ended_at >= range_start)),
    ).order_by(ActivitySession.started_at, ActivitySession.id)).all())
    timer_ids = {row.time_session_id for row in session_rows if row.time_session_id is not None}
    segment_rows = list(db.scalars(select(TimeSessionSegment).where(
        TimeSessionSegment.user_id == user.id,
        TimeSessionSegment.time_session_id.in_(timer_ids),
        TimeSessionSegment.ended_at.is_not(None),
    ).order_by(TimeSessionSegment.started_at)).all()) if timer_ids else []
    segments_by_timer = defaultdict(list)
    for segment in segment_rows:
        segments_by_timer[segment.time_session_id].append((segment.started_at, segment.ended_at))

    confirmed_by_id = {}
    corrected_by_id = {}
    drafts_by_id = {}
    session_crosses_day = {}
    session_duration_available = {}
    unavailable_legacy_seconds = 0
    per_session_intervals = {}
    for row in session_rows:
        intervals = []
        if row.time_session_id is not None:
            intervals = segments_by_timer.get(row.time_session_id, [])
            session_duration_available[row.id] = bool(intervals)
            if row.status in ("confirmed", "corrected") and not intervals and row.duration_seconds:
                unavailable_legacy_seconds += row.duration_seconds
        elif row.duration_seconds and row.ended_at is not None:
            intervals = [(row.started_at, row.started_at + timedelta(seconds=row.duration_seconds))]
            session_duration_available[row.id] = True
        else:
            session_duration_available[row.id] = row.duration_seconds is not None
        session_crosses_day[row.id] = any(left < range_start or right > range_end for left, right in intervals)
        clipped = _clip_intervals(intervals, range_start, range_end)
        if row.status == "confirmed":
            confirmed_by_id[row.id] = clipped
            per_session_intervals[row.id] = clipped
        elif row.status == "corrected":
            corrected_by_id[row.id] = clipped
            per_session_intervals[row.id] = clipped
        elif row.status == "draft":
            drafts_by_id[row.id] = clipped

    confirmed_seconds = union_seconds([i for rows in confirmed_by_id.values() for i in rows])
    corrected_seconds = union_seconds([i for rows in corrected_by_id.values() for i in rows])
    all_verified = [i for rows in per_session_intervals.values() for i in rows]
    actual_seconds = union_seconds(all_verified)
    draft_seconds = union_seconds([i for rows in drafts_by_id.values() for i in rows])

    planned_intervals = [(item.start_at.astimezone(UTC), item.end_at.astimezone(UTC)) for item in schedules if item.status != "cancelled"]
    actual_clipped = _clip_intervals(all_verified, range_start, range_end)
    scheduled_seconds = _overlap_seconds(actual_clipped, planned_intervals)
    outside_planned_seconds = max(0, actual_seconds - scheduled_seconds)
    overlap_seconds = _multi_session_overlap_seconds(per_session_intervals)

    session_ids = list(per_session_intervals)
    allocation_rows = db.execute(select(
        ActivityGoalContribution.activity_session_id,
        func.sum(ActivityGoalContribution.contribution_value),
    ).where(
        ActivityGoalContribution.user_id == user.id,
        ActivityGoalContribution.activity_session_id.in_(session_ids),
        ActivityGoalContribution.contribution_type == "time",
        ActivityGoalContribution.reversed_at.is_(None),
    ).group_by(ActivityGoalContribution.activity_session_id)).all() if session_ids else []
    allocation_claims = {sid: int(value) for sid, value in allocation_rows}
    ambiguous_allocations = 0
    allocated_seconds = 0
    for session_id, claimed in allocation_claims.items():
        intervals = per_session_intervals.get(session_id, [])
        ambiguous = session_crosses_day.get(session_id, False) or not intervals or any(
            left < other_right and right > other_left
            for other_id, other_intervals in per_session_intervals.items() if other_id != session_id
            for left, right in intervals for other_left, other_right in other_intervals
        )
        if ambiguous:
            ambiguous_allocations += claimed
        else:
            allocated_seconds += claimed
    unallocated_seconds = None if ambiguous_allocations else max(0, actual_seconds - allocated_seconds)

    activity_record_rows = list(db.scalars(select(ActivityRecord).where(
        ActivityRecord.user_id == user.id,
        ActivityRecord.recorded_at >= range_start,
        ActivityRecord.recorded_at < range_end,
    ).order_by(ActivityRecord.recorded_at, ActivityRecord.id)).all())
    report_session_ids = [row.id for row in session_rows]
    contributions = list(db.scalars(select(ActivityGoalContribution).where(
        ActivityGoalContribution.user_id == user.id,
        ((ActivityGoalContribution.activity_session_id.in_(report_session_ids)) if report_session_ids else False) |
        ((ActivityGoalContribution.activity_record_id.in_([row.id for row in activity_record_rows])) if activity_record_rows else False) |
        ((ActivityGoalContribution.created_at >= range_start) & (ActivityGoalContribution.created_at < range_end)) |
        ((ActivityGoalContribution.reversed_at >= range_start) & (ActivityGoalContribution.reversed_at < range_end)),
    ).order_by(ActivityGoalContribution.created_at, ActivityGoalContribution.id)).all()) if (report_session_ids or activity_record_rows) else []

    goal_ids = {row.goal_id for row in contributions if row.goal_id is not None}
    progress_entries = list(db.scalars(select(GoalProgressEntry).where(
        GoalProgressEntry.user_id == user.id,
        GoalProgressEntry.created_at >= range_start,
        GoalProgressEntry.created_at < range_end,
    ).order_by(GoalProgressEntry.created_at, GoalProgressEntry.id)).all())
    goal_ids.update(row.goal_id for row in progress_entries)
    goals = list(db.scalars(select(AmbitionGoal).where(AmbitionGoal.user_id == user.id, AmbitionGoal.id.in_(goal_ids))).all()) if goal_ids else []
    goal_map = {row.id: row for row in goals}
    ambition_ids = {row.ambition_id for row in goals}
    ambitions = list(db.scalars(select(Ambition).where(Ambition.user_id == user.id, Ambition.id.in_(ambition_ids))).all()) if ambition_ids else []
    ambition_map = {row.id: row for row in ambitions}
    target_ids = {row.target_id for row in contributions if row.target_id is not None}
    targets = list(db.scalars(select(Target).where(Target.user_id == user.id, Target.id.in_(target_ids))).all()) if target_ids else []
    target_map = {row.id: row for row in targets}

    contribution_counts = defaultdict(int)
    contribution_goals = {}
    evidence_counts = {}
    if report_session_ids:
        evidence_counts = dict(db.execute(select(
            ActivitySessionEvent.activity_session_id,
            func.count(ActivitySessionEvent.activity_event_id),
        ).where(
            ActivitySessionEvent.user_id == user.id,
            ActivitySessionEvent.activity_session_id.in_(report_session_ids),
        ).group_by(ActivitySessionEvent.activity_session_id)).all())
    for contribution in contributions:
        if contribution.activity_session_id:
            contribution_counts[contribution.activity_session_id] += 1
            if contribution.goal_id is not None:
                contribution_goals.setdefault(contribution.activity_session_id, str(contribution.goal_id))

    task_history_rows = list(db.scalars(select(TaskStatusEvent).where(
        TaskStatusEvent.user_id == user.id,
        TaskStatusEvent.created_at >= range_start,
        TaskStatusEvent.created_at < range_end,
    ).order_by(TaskStatusEvent.created_at, TaskStatusEvent.id)).all())
    schedule_history_rows = list(db.scalars(select(ScheduleStatusEvent).where(
        ScheduleStatusEvent.user_id == user.id,
        ScheduleStatusEvent.created_at >= range_start,
        ScheduleStatusEvent.created_at < range_end,
    ).order_by(ScheduleStatusEvent.created_at, ScheduleStatusEvent.id)).all())
    corrections = list(db.scalars(select(ActivityCorrection).where(
        ActivityCorrection.user_id == user.id,
        ActivityCorrection.created_at >= range_start,
        ActivityCorrection.created_at < range_end,
    ).order_by(ActivityCorrection.created_at, ActivityCorrection.id)).all())

    diary = db.scalars(select(DiaryEntry).where(DiaryEntry.user_id == user.id, DiaryEntry.entry_date == report_date)).first()
    unlinked_events = db.scalar(select(func.count(ActivityEvent.id)).where(
        ActivityEvent.user_id == user.id,
        ActivityEvent.occurred_at >= range_start,
        ActivityEvent.occurred_at < range_end,
        ActivityEvent.discarded_at.is_(None),
        ~exists(select(1).where(ActivitySessionEvent.user_id == user.id, ActivitySessionEvent.activity_event_id == ActivityEvent.id)),
    )) or 0

    statuses = lambda rows, value: sum(row.status == value for row in rows)
    return DailyReport(
        date=report_date,
        timezone=str(timezone),
        planned=DailyPlannedSummary(
            planned_seconds=sum(seconds_between(a, b) for a, b in planned_intervals),
            scheduled_blocks=sum(item.status != "cancelled" for item in schedules),
            completed_blocks=statuses(schedules, "completed"), partial_blocks=statuses(schedules, "partial"),
            skipped_blocks=statuses(schedules, "skipped"), missed_blocks=statuses(schedules, "missed"), cancelled_blocks=statuses(schedules, "cancelled"),
            planned_tasks=len(tasks), completed_tasks=statuses(tasks, "completed"), in_progress_tasks=statuses(tasks, "in_progress"),
            blocked_tasks=statuses(tasks, "blocked"), cancelled_tasks=statuses(tasks, "cancelled"),
        ),
        actual=DailyActualSummary(
            confirmed_seconds=confirmed_seconds, corrected_seconds=corrected_seconds, actual_seconds=actual_seconds,
            draft_seconds=draft_seconds, allocated_seconds=allocated_seconds, unallocated_seconds=unallocated_seconds,
            outside_planned_seconds=outside_planned_seconds, ambiguous_seconds=overlap_seconds,
            overlapping_actual_seconds=overlap_seconds, ambiguous_allocation_seconds=ambiguous_allocations,
            confirmed_session_count=len(confirmed_by_id), corrected_session_count=len(corrected_by_id),
            unavailable_legacy_seconds=unavailable_legacy_seconds,
        ),
        activities=[DailyActivity(
            id=str(row.id), title=row.title, status=row.status, source_kind=row.source_kind, started_at=row.started_at,
            ended_at=row.ended_at,
            duration_seconds=(
                None if not session_duration_available.get(row.id, False)
                else (union_seconds(per_session_intervals[row.id]) if row.id in per_session_intervals else (union_seconds(drafts_by_id[row.id]) if row.id in drafts_by_id else None))
            ),
            contribution_count=contribution_counts[row.id], schedule_item_id=str(row.schedule_item_id) if row.schedule_item_id else None,
            evidence_event_count=evidence_counts.get(row.id, 0),
            task_id=str(row.task_id) if row.task_id else None,
            goal_id=contribution_goals.get(row.id),
            target_id=str(row.target_id) if row.target_id else None,
        ) for row in session_rows],
        historical_activities=[DailyHistoricalActivity(
            id=str(row.id), title=row.title, activity_type=row.activity_type, metric_value=row.metric_value,
            recorded_at=row.recorded_at, time_session_id=str(row.time_session_id) if row.time_session_id else None,
        ) for row in activity_record_rows],
        goal_contributions=[DailyGoalContribution(
            id=str(row.id), contribution_type=row.contribution_type, value=str(row.contribution_value), unit=row.unit,
            goal_id=str(row.goal_id) if row.goal_id else None,
            goal_title=goal_map[row.goal_id].title if row.goal_id in goal_map else None,
            ambition_title=ambition_map[goal_map[row.goal_id].ambition_id].title if row.goal_id in goal_map and goal_map[row.goal_id].ambition_id in ambition_map else None,
            target_id=str(row.target_id) if row.target_id else None, target_title=target_map[row.target_id].title if row.target_id in target_map else None,
            activity_session_id=str(row.activity_session_id) if row.activity_session_id else None,
            activity_record_id=str(row.activity_record_id) if row.activity_record_id else None,
            reversed_at=row.reversed_at, created_at=row.created_at,
        ) for row in contributions],
        goal_progress_history=[DailyGoalProgress(
            id=str(row.id), goal_id=str(row.goal_id), goal_title=goal_map[row.goal_id].title if row.goal_id in goal_map else "Unavailable goal",
            numeric_delta=str(row.numeric_delta) if row.numeric_delta is not None else None,
            resulting_value=str(row.resulting_value) if row.resulting_value is not None else None,
            qualitative_value=row.qualitative_value, unit=row.unit, source_kind=row.source_kind,
            corrects_entry_id=str(row.corrects_entry_id) if row.corrects_entry_id else None, reason=row.reason, created_at=row.created_at,
        ) for row in progress_entries],
        tasks=[DailyTask(id=str(row.id), title=row.title, status=row.status, due_at=row.due_at, priority=row.priority) for row in tasks],
        schedule=schedules,
        task_history=[DailyStatusChange(item_id=str(row.task_id), previous_status=row.previous_status, new_status=row.new_status, event_kind=row.event_kind, created_at=row.created_at) for row in task_history_rows],
        schedule_history=[DailyStatusChange(item_id=str(row.schedule_item_id), previous_status=row.previous_status, new_status=row.new_status, event_kind=row.event_kind, created_at=row.created_at) for row in schedule_history_rows],
        activity_corrections=[DailyActivityCorrection(
            id=str(row.id), activity_session_id=str(row.activity_session_id), field_name=row.field_name,
            previous_value=row.previous_value, new_value=row.new_value, reason=row.reason, created_at=row.created_at,
        ) for row in corrections],
        reflection=DailyReflection(
            available=diary is not None, has_accomplishments=bool(diary and diary.accomplishments and diary.accomplishments.strip()),
            has_learning=bool(diary and diary.learned and diary.learned.strip()), has_distractions=bool(diary and diary.distractions and diary.distractions.strip()),
            has_tomorrow_changes=bool(diary and diary.tomorrow_changes and diary.tomorrow_changes.strip()),
        ),
        data_quality=DailyDataQuality(
            draft_session_count=sum(row.status == "draft" for row in session_rows),
            discarded_session_count=sum(row.status == "discarded" for row in session_rows),
            superseded_session_count=sum(row.status == "superseded" for row in session_rows),
            unlinked_observation_count=int(unlinked_events), legacy_activity_record_count=len(activity_record_rows),
            unavailable_legacy_seconds=unavailable_legacy_seconds, ambiguous_allocation_seconds=ambiguous_allocations,
        ),
    )


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
    confirmed_by_day = {day: [] for day in days}
    corrected_by_day = {day: [] for day in days}
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
    timer_ids = {row.time_session_id for row in sessions if row.time_session_id is not None}
    session_segments = list(db.scalars(select(TimeSessionSegment).where(
        TimeSessionSegment.user_id == user.id,
        TimeSessionSegment.time_session_id.in_(timer_ids),
        TimeSessionSegment.ended_at.is_not(None),
    ).order_by(TimeSessionSegment.started_at, TimeSessionSegment.id)).all()) if timer_ids else []
    segments_by_timer = defaultdict(list)
    for segment in session_segments:
        if segment.ended_at > segment.started_at:
            segments_by_timer[segment.time_session_id].append((segment.started_at, segment.ended_at))
    for session in sessions:
        intervals: list[tuple[datetime, datetime]] = []
        if session.time_session_id is not None:
            intervals.extend(segments_by_timer.get(session.time_session_id, []))
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
                    if session.status == "confirmed":
                        confirmed_by_day[day].append((cursor, part_end))
                    elif session.status == "corrected":
                        corrected_by_day[day].append((cursor, part_end))
                    label, normalized_key = canonical_label(session.title)
                    category_key = f"activity_session:{session.source_kind}:{normalized_key}"
                    category_intervals[category_key].append((cursor, part_end))
                cursor = part_end
    for day in days:
        actual_by_day[day] = union_seconds(actual_intervals[day])
    confirmed_seconds = sum(union_seconds(confirmed_by_day[day]) for day in days)
    corrected_seconds = sum(union_seconds(corrected_by_day[day]) for day in days)

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
    ambiguous_actual_seconds = _multi_session_overlap_seconds({
        session_id: _clip_intervals(intervals, range_start, range_end)
        for session_id, intervals in session_actual_intervals.items()
    })
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
    draft_timer_ids = {row.time_session_id for row in drafts if row.time_session_id is not None}
    draft_segments = list(db.scalars(select(TimeSessionSegment).where(
        TimeSessionSegment.user_id == user.id,
        TimeSessionSegment.time_session_id.in_(draft_timer_ids),
        TimeSessionSegment.ended_at.is_not(None),
    ).order_by(TimeSessionSegment.started_at, TimeSessionSegment.id)).all()) if draft_timer_ids else []
    draft_segments_by_timer = defaultdict(list)
    for segment in draft_segments:
        if segment.ended_at > segment.started_at:
            draft_segments_by_timer[segment.time_session_id].append((segment.started_at, segment.ended_at))
    for session in drafts:
        if session.time_session_id is not None:
            draft_intervals = draft_segments_by_timer.get(session.time_session_id, [])
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
            confirmed_seconds=confirmed_seconds,
            corrected_seconds=corrected_seconds,
            ambiguous_actual_seconds=ambiguous_actual_seconds,
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
                confirmed_seconds=union_seconds(confirmed_by_day[day]),
                corrected_seconds=union_seconds(corrected_by_day[day]),
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


def _change_metric(current: int, previous: int | None) -> PeriodComparisonMetric:
    if previous is None:
        return PeriodComparisonMetric(current=current, previous=None, change=None, percent_change=None)
    change = current - previous
    percent = round((change / previous) * 100, 2) if previous else None
    return PeriodComparisonMetric(current=current, previous=previous, change=change, percent_change=percent)


def _period_report(start: date, end: date, previous_start: date, previous_end: date, period_type: str, db: Session, user: User) -> PeriodReport:
    if end < start or (end - start).days > 30:
        raise HTTPException(422, "Reporting period must contain between 1 and 31 calendar days.")
    timezone = user_timezone(db, user.id)
    current = summary(start, end, db, user)
    previous = summary(previous_start, previous_end, db, user)
    schedule_execution = schedule_execution_summary(start, end, db, user)
    range_start = datetime.combine(start, time.min, timezone).astimezone(UTC)
    range_end = datetime.combine(end + timedelta(days=1), time.min, timezone).astimezone(UTC)
    prev_start = datetime.combine(previous_start, time.min, timezone).astimezone(UTC)
    prev_end = datetime.combine(previous_end + timedelta(days=1), time.min, timezone).astimezone(UTC)

    task_events = list(db.scalars(select(TaskStatusEvent).where(
        TaskStatusEvent.user_id == user.id, TaskStatusEvent.created_at >= range_start,
        TaskStatusEvent.created_at < range_end,
    )).all())
    task_status_counts = {status: sum(row.new_status == status for row in task_events) for status in ("planned", "in_progress", "completed", "blocked", "cancelled")}
    previous_completed_tasks = db.scalar(select(func.count(TaskStatusEvent.id)).where(
        TaskStatusEvent.user_id == user.id, TaskStatusEvent.created_at >= prev_start,
        TaskStatusEvent.created_at < prev_end, TaskStatusEvent.event_kind == "changed",
        TaskStatusEvent.new_status == "completed",
    )) or 0

    contributions = list(db.scalars(select(ActivityGoalContribution).where(
        ActivityGoalContribution.user_id == user.id,
        ((ActivityGoalContribution.created_at >= range_start) & (ActivityGoalContribution.created_at < range_end)) |
        ((ActivityGoalContribution.reversed_at >= range_start) & (ActivityGoalContribution.reversed_at < range_end)),
    ).order_by(ActivityGoalContribution.created_at, ActivityGoalContribution.id)).all())
    previous_contributions = db.scalar(select(func.count(ActivityGoalContribution.id)).where(
        ActivityGoalContribution.user_id == user.id,
        ((ActivityGoalContribution.created_at >= prev_start) & (ActivityGoalContribution.created_at < prev_end)) |
        ((ActivityGoalContribution.reversed_at >= prev_start) & (ActivityGoalContribution.reversed_at < prev_end)),
    )) or 0
    progress_entries = list(db.scalars(select(GoalProgressEntry).where(
        GoalProgressEntry.user_id == user.id,
        GoalProgressEntry.created_at >= range_start, GoalProgressEntry.created_at < range_end,
    ).order_by(GoalProgressEntry.created_at, GoalProgressEntry.id)).all())
    previous_progress = db.scalar(select(func.count(GoalProgressEntry.id)).where(
        GoalProgressEntry.user_id == user.id,
        GoalProgressEntry.created_at >= prev_start, GoalProgressEntry.created_at < prev_end,
    )) or 0
    milestone_rows = list(db.scalars(select(AmbitionMilestone).where(
        AmbitionMilestone.user_id == user.id,
        AmbitionMilestone.status == "completed",
        AmbitionMilestone.completed_at >= start, AmbitionMilestone.completed_at <= end,
    ).order_by(AmbitionMilestone.completed_at, AmbitionMilestone.id)).all())
    ambition_changes = list(db.scalars(select(AmbitionLifecycleEvent).where(
        AmbitionLifecycleEvent.user_id == user.id,
        AmbitionLifecycleEvent.created_at >= range_start,
        AmbitionLifecycleEvent.created_at < range_end,
    ).order_by(AmbitionLifecycleEvent.created_at, AmbitionLifecycleEvent.id)).all())
    task_changes = db.scalar(select(func.count(TaskStatusEvent.id)).where(
        TaskStatusEvent.user_id == user.id, TaskStatusEvent.created_at >= range_start,
        TaskStatusEvent.created_at < range_end,
    )) or 0
    previous_task_changes = db.scalar(select(func.count(TaskStatusEvent.id)).where(
        TaskStatusEvent.user_id == user.id, TaskStatusEvent.created_at >= prev_start,
        TaskStatusEvent.created_at < prev_end,
    )) or 0
    schedule_changes = db.scalar(select(func.count(ScheduleStatusEvent.id)).where(
        ScheduleStatusEvent.user_id == user.id, ScheduleStatusEvent.created_at >= range_start,
        ScheduleStatusEvent.created_at < range_end,
    )) or 0
    previous_schedule_changes = db.scalar(select(func.count(ScheduleStatusEvent.id)).where(
        ScheduleStatusEvent.user_id == user.id, ScheduleStatusEvent.created_at >= prev_start,
        ScheduleStatusEvent.created_at < prev_end,
    )) or 0
    activity_correction_count = db.scalar(select(func.count(ActivityCorrection.id)).where(
        ActivityCorrection.user_id == user.id, ActivityCorrection.created_at >= range_start,
        ActivityCorrection.created_at < range_end,
    )) or 0
    reflection_days = current.reflection.days_with_entries
    previous_reflection_days = previous.reflection.days_with_entries
    goal_ids = {row.goal_id for row in contributions if row.goal_id is not None}
    goal_ids.update(row.goal_id for row in progress_entries)
    goals = list(db.scalars(select(AmbitionGoal).where(
        AmbitionGoal.user_id == user.id, AmbitionGoal.id.in_(goal_ids),
    )).all()) if goal_ids else []
    goal_map = {row.id: row for row in goals}
    ambition_ids = {row.ambition_id for row in goals}
    ambition_rows = list(db.scalars(select(Ambition).where(
        Ambition.user_id == user.id, Ambition.id.in_(ambition_ids),
    )).all()) if ambition_ids else []
    ambition_map = {row.id: row for row in ambition_rows}
    target_ids = {row.target_id for row in contributions if row.target_id is not None}
    targets = list(db.scalars(select(Target).where(
        Target.user_id == user.id, Target.id.in_(target_ids),
    )).all()) if target_ids else []
    target_map = {row.id: row for row in targets}

    def contribution_view(row: ActivityGoalContribution) -> HistoricalProgressItem:
        return HistoricalProgressItem(
            id=str(row.id), goal_id=str(row.goal_id) if row.goal_id else None,
            goal_title=goal_map[row.goal_id].title if row.goal_id in goal_map else None,
            ambition_title=ambition_map[goal_map[row.goal_id].ambition_id].title if row.goal_id in goal_map and goal_map[row.goal_id].ambition_id in ambition_map else None,
            target_id=str(row.target_id) if row.target_id else None,
            target_title=target_map[row.target_id].title if row.target_id in target_map else None,
            contribution_type=row.contribution_type, value=str(row.contribution_value), unit=row.unit,
            source_kind="activity_contribution", recorded_at=row.created_at, reversed_at=row.reversed_at,
        )

    def progress_view(row: GoalProgressEntry) -> HistoricalProgressItem:
        return HistoricalProgressItem(
            id=str(row.id), goal_id=str(row.goal_id), source_kind=row.source_kind,
            goal_title=goal_map[row.goal_id].title if row.goal_id in goal_map else None,
            ambition_title=ambition_map[goal_map[row.goal_id].ambition_id].title if row.goal_id in goal_map and goal_map[row.goal_id].ambition_id in ambition_map else None,
            value=str(row.numeric_delta) if row.numeric_delta is not None else None,
            numeric_delta=str(row.numeric_delta) if row.numeric_delta is not None else None,
            unit=row.unit, recorded_at=row.created_at, qualitative_value=row.qualitative_value,
            created_at=row.created_at, reason=row.reason,
            resulting_value=str(row.resulting_value) if row.resulting_value is not None else None,
            corrects_entry_id=str(row.corrects_entry_id) if row.corrects_entry_id else None,
            source_contribution_id=str(row.source_contribution_id) if row.source_contribution_id else None,
        )

    return PeriodReport(
        period_type=period_type, start_date=start, end_date=end, timezone=str(timezone),
        totals=current.totals, daily=current.daily,
        days_with_confirmed_or_corrected_activity=sum(day.actual_seconds > 0 for day in current.daily),
        days_with_planned_activity=sum(day.planned_seconds > 0 for day in current.daily),
        days_with_no_recorded_activity=sum(day.actual_seconds == 0 and day.activity_count == 0 and day.draft_seconds == 0 for day in current.daily),
        outside_planned_seconds=schedule_execution.totals.outside_planned_seconds,
        schedule_ambiguous_seconds=schedule_execution.totals.ambiguous_actual_seconds,
        task_status_transitions=task_status_counts, activity_distribution=current.breakdown,
        contribution_count=len(contributions), contributions=[contribution_view(row) for row in contributions],
        progress_entries=[progress_view(row) for row in progress_entries],
        milestones=[HistoricalMilestone(id=str(row.id), goal_id=str(row.goal_id), title=row.title, status=row.status, completed_at=row.completed_at) for row in milestone_rows],
        ambition_status_changes=[{
            "ambition_id": str(row.ambition_id), "previous_status": row.previous_status,
            "new_status": row.new_status, "reason": row.reason, "recorded_at": row.created_at.isoformat(),
        } for row in ambition_changes],
        task_status_change_count=task_changes, schedule_status_change_count=schedule_changes,
        activity_correction_count=int(activity_correction_count),
        reflection_days=reflection_days,
        reflection_coverage_percent=round(reflection_days / len(current.daily) * 100, 2) if current.daily else 0,
        comparison={
            "planned_seconds": _change_metric(current.totals.planned_seconds, previous.totals.planned_seconds),
            "confirmed_actual_seconds": _change_metric(current.totals.confirmed_seconds, previous.totals.confirmed_seconds),
            "completed_tasks": _change_metric(sum(row.event_kind == "changed" and row.new_status == "completed" for row in task_events), int(previous_completed_tasks)),
            "activity_contributions": _change_metric(len(contributions), int(previous_contributions)),
            "goal_progress_entries": _change_metric(len(progress_entries), int(previous_progress)),
            "reflection_days": _change_metric(reflection_days, previous_reflection_days),
            "task_status_changes": _change_metric(task_changes, previous_task_changes),
            "schedule_status_changes": _change_metric(schedule_changes, previous_schedule_changes),
        },
        history_limitations=[
            "Starting goal values are unavailable unless explicitly recorded in progress history.",
            "Past goal status and milestone reopen/recompletion transitions are not retained by the current data model.",
            "Targets retain current period values rather than immutable past value snapshots.",
            "Legacy activity records retain their historical meaning and are not verified time.",
        ],
    )


@router.get("/weekly-report", response_model=PeriodReport)
def weekly_report(
    week_start: date = Query(), db: Session = Depends(get_db), user: User = Depends(get_current_user),
) -> PeriodReport:
    if week_start.weekday() != 0:
        raise HTTPException(422, "week_start must be a Monday in the profile-local calendar.")
    return _period_report(week_start, week_start + timedelta(days=6), week_start - timedelta(days=7), week_start - timedelta(days=1), "week", db, user)


@router.get("/monthly-report", response_model=PeriodReport)
def monthly_report(
    month: str = Query(pattern=r"^\d{4}-\d{2}$"), db: Session = Depends(get_db), user: User = Depends(get_current_user),
) -> PeriodReport:
    try:
        year, month_number = (int(value) for value in month.split("-"))
        start = date(year, month_number, 1)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, "month must be a valid calendar month in YYYY-MM format.") from exc
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    previous_end = start - timedelta(days=1)
    previous_start = previous_end.replace(day=1)
    return _period_report(start, end, previous_start, previous_end, "month", db, user)


@router.get("/ambitions/goals/{goal_id}/history", response_model=GoalHistoryRead)
def goal_history(
    goal_id: UUID, start_date: date | None = Query(default=None), end_date: date | None = Query(default=None),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
) -> GoalHistoryRead:
    timezone = user_timezone(db, user.id)
    end = end_date or datetime.now(timezone).date()
    start = start_date or end - timedelta(days=365)
    if end < start or (end - start).days > 365:
        raise HTTPException(422, "Goal history range must contain between 1 and 366 calendar days.")
    goal = db.scalar(select(AmbitionGoal).where(AmbitionGoal.id == goal_id, AmbitionGoal.user_id == user.id))
    if goal is None:
        raise HTTPException(404, "Goal not found.")
    start_at = datetime.combine(start, time.min, timezone).astimezone(UTC)
    end_at = datetime.combine(end + timedelta(days=1), time.min, timezone).astimezone(UTC)
    entries = list(db.scalars(select(GoalProgressEntry).where(
        GoalProgressEntry.user_id == user.id, GoalProgressEntry.goal_id == goal.id,
        GoalProgressEntry.created_at >= start_at, GoalProgressEntry.created_at < end_at,
    ).order_by(GoalProgressEntry.created_at, GoalProgressEntry.id)).all())
    contribution_rows = list(db.scalars(select(ActivityGoalContribution).where(
        ActivityGoalContribution.user_id == user.id, ActivityGoalContribution.goal_id == goal.id,
        ((ActivityGoalContribution.created_at >= start_at) & (ActivityGoalContribution.created_at < end_at)) |
        ((ActivityGoalContribution.reversed_at >= start_at) & (ActivityGoalContribution.reversed_at < end_at)),
    ).order_by(ActivityGoalContribution.created_at, ActivityGoalContribution.id)).all())
    milestones = list(db.scalars(select(AmbitionMilestone).where(
        AmbitionMilestone.user_id == user.id, AmbitionMilestone.goal_id == goal.id,
        ((AmbitionMilestone.created_at >= start_at) & (AmbitionMilestone.created_at < end_at)) |
        ((AmbitionMilestone.completed_at >= start) & (AmbitionMilestone.completed_at <= end)),
    ).order_by(AmbitionMilestone.created_at, AmbitionMilestone.id)).all())
    lifecycle = list(db.scalars(select(AmbitionLifecycleEvent).where(
        AmbitionLifecycleEvent.user_id == user.id, AmbitionLifecycleEvent.ambition_id == goal.ambition_id,
        AmbitionLifecycleEvent.created_at >= start_at, AmbitionLifecycleEvent.created_at < end_at,
    ).order_by(AmbitionLifecycleEvent.created_at, AmbitionLifecycleEvent.id)).all())
    return GoalHistoryRead(
        goal_id=str(goal.id), ambition_id=str(goal.ambition_id), title=goal.title, status=goal.status,
        measurement_type=goal.measurement_type, measurement_unit=goal.measurement_unit,
        current_value=str(goal.current_value) if goal.measurement_type != "qualitative" else None,
        qualitative_value=goal.qualitative_value, starting_value=None, starting_value_status="not_recorded",
        progress_entries=[HistoricalProgressItem(
            id=str(row.id), goal_id=str(row.goal_id), source_kind=row.source_kind,
            value=str(row.numeric_delta) if row.numeric_delta is not None else None, unit=row.unit,
            numeric_delta=str(row.numeric_delta) if row.numeric_delta is not None else None,
            recorded_at=row.created_at, created_at=row.created_at, qualitative_value=row.qualitative_value,
            reason=row.reason,
            resulting_value=str(row.resulting_value) if row.resulting_value is not None else None,
            corrects_entry_id=str(row.corrects_entry_id) if row.corrects_entry_id else None,
            source_contribution_id=str(row.source_contribution_id) if row.source_contribution_id else None,
        ) for row in entries],
        contributions=[HistoricalProgressItem(
            id=str(row.id), goal_id=str(row.goal_id), contribution_type=row.contribution_type,
            value=str(row.contribution_value), unit=row.unit, source_kind="activity_contribution",
            recorded_at=row.created_at, reversed_at=row.reversed_at,
        ) for row in contribution_rows],
        milestones=[HistoricalMilestone(id=str(row.id), goal_id=str(row.goal_id), title=row.title, status=row.status, completed_at=row.completed_at) for row in milestones],
        ambition_status_history=[{
            "previous_status": row.previous_status, "new_status": row.new_status,
            "reason": row.reason, "recorded_at": row.created_at.isoformat(),
        } for row in lifecycle],
        goal_status_history_available=False, milestone_status_history_available=False,
        limitations=[
            "No starting value was recorded; historical values are limited to explicit progress entries.",
            "Goal status changes and milestone reopen/recompletion transitions are not historically stored.",
            "Targets retain current values rather than immutable historical values.",
            "Only the requested bounded date range is included.",
        ],
    )

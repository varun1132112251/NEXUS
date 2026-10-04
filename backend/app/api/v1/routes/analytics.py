from collections import defaultdict
from datetime import UTC, date, datetime, time
import re
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import get_current_user
from app.db.session import get_db
from app.models.activity_record import ActivityRecord
from app.models.diary import DiaryEntry
from app.models.schedule import ScheduleItem
from app.models.target import Target
from app.models.time_session import TimeSession
from app.models.user import User
from app.schemas.analytics import (
    ActivityBreakdown,
    AnalyticsDay,
    AnalyticsSummary,
    AnalyticsTotals,
    ReflectionSummary,
    TargetProgress,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])
LOCAL_TZ = ZoneInfo("Asia/Kolkata")


def local_day(dt: datetime) -> date:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(LOCAL_TZ).date()


def seconds_between(start: datetime, end: datetime) -> int:
    return max(0, int((end - start).total_seconds()))


def canonical_label(value: str | None) -> tuple[str, str]:
    label = re.sub(r"\s+", " ", (value or "Unlinked").strip())
    return label, label.casefold()


def build_insights(
    planned_seconds: int,
    actual_seconds: int,
    planned_items: int,
    completed_items: int,
    diary_days: int,
    range_days: int,
    breakdown: list[dict],
) -> list[str]:
    insights: list[str] = []
    if planned_items == 0 and actual_seconds == 0:
        insights.append("No execution evidence in this range yet.")
        return insights
    schedule_rate = (completed_items / planned_items) * 100 if planned_items else 0
    time_rate = (actual_seconds / planned_seconds) * 100 if planned_seconds else 0
    if planned_items and schedule_rate < 70:
        insights.append(f"Schedule completion is {schedule_rate:.0f}%; reduce or reschedule low-priority blocks.")
    elif planned_items and schedule_rate >= 90:
        insights.append("Schedule completion is strong; preserve the current planning load.")
    if planned_seconds and time_rate < 60:
        insights.append(f"Focused time is {time_rate:.0f}% of planned time; protect planned focus blocks more aggressively.")
    elif planned_seconds and time_rate > 110:
        insights.append("Focused time exceeds planned time; check whether important work is being left outside the schedule.")
    if diary_days == 0:
        insights.append("No reflections recorded; add a short daily reflection to preserve learning and context.")
    elif diary_days < range_days:
        insights.append(f"Reflection coverage is {diary_days}/{range_days} days; keep the nightly review consistent.")
    if breakdown:
        top = breakdown[0]
        if top["seconds"] > 0:
            insights.append(f"Most focused time went to {top['label']} ({top['seconds'] // 60}m).")
    return insights


@router.get("/summary", response_model=AnalyticsSummary)
def summary(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AnalyticsSummary:
    today = datetime.now(LOCAL_TZ).date()
    start = start_date or today
    end = end_date or start
    if end < start:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="end_date must be on or after start_date.")

    schedules = list(db.scalars(select(ScheduleItem).where(
        ScheduleItem.user_id == user.id,
        ScheduleItem.scheduled_date >= start,
        ScheduleItem.scheduled_date <= end,
    )).all())

    range_start = datetime.combine(start, time.min, LOCAL_TZ).astimezone(UTC)
    range_end = datetime.combine(end, time.max, LOCAL_TZ).astimezone(UTC)

    sessions = list(db.scalars(select(TimeSession).where(
        TimeSession.user_id == user.id,
        TimeSession.status == "completed",
        TimeSession.started_at < range_end,
        TimeSession.ended_at.is_not(None),
        TimeSession.ended_at >= range_start,
    )).all())

    activities = list(db.scalars(select(ActivityRecord).where(
        ActivityRecord.user_id == user.id,
        ActivityRecord.recorded_at >= range_start,
        ActivityRecord.recorded_at <= range_end,
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

    for item in schedules:
        day = item.scheduled_date
        planned_by_day[day] += seconds_between(item.start_at, item.end_at)
        planned_items_by_day[day] += 1
        if item.status == "completed":
            completed_items_by_day[day] += 1

    for session in sessions:
        day = local_day(session.started_at)
        if day in actual_by_day:
            actual_by_day[day] += session.duration_seconds or 0

    for activity in activities:
        day = local_day(activity.recorded_at)
        if day in activity_by_day:
            activity_by_day[day] += 1

    planned_items = len(schedules)
    completed_items = sum(completed_items_by_day.values())
    skipped_items = sum(1 for item in schedules if item.status == "skipped")
    planned_seconds = sum(planned_by_day.values())
    actual_seconds = sum(actual_by_day.values())
    schedule_rate = round((completed_items / planned_items) * 100, 2) if planned_items else 0.0
    time_rate = round((actual_seconds / planned_seconds) * 100, 2) if planned_seconds else 0.0

    targets = list(db.scalars(select(Target).where(
        Target.user_id == user.id,
        Target.month >= start.replace(day=1),
        Target.month <= end.replace(day=1),
    ).order_by(Target.month, Target.created_at)).all())

    breakdown_map = defaultdict(lambda: {"label": "", "seconds": 0, "session_count": 0, "activity_count": 0, "metric_total": 0})
    for session in sessions:
        label, key = canonical_label(session.title)
        bucket = breakdown_map[key]
        bucket["label"] = bucket["label"] or label
        bucket["seconds"] += session.duration_seconds or 0
        bucket["session_count"] += 1
    for activity in activities:
        label, key = canonical_label(activity.title)
        bucket = breakdown_map[key]
        bucket["label"] = bucket["label"] or label
        bucket["activity_count"] += 1
        bucket["metric_total"] += activity.metric_value or 0

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
        )
        for key, value in sorted(breakdown_map.items(), key=lambda item: item[1]["seconds"], reverse=True)
    ]

    insights = build_insights(
        planned_seconds, actual_seconds, planned_items, completed_items,
        len(diaries), len(days), breakdown_map and [x.model_dump() for x in breakdown] or [],
    )

    return AnalyticsSummary(
        start_date=start,
        end_date=end,
        totals=AnalyticsTotals(
            planned_seconds=planned_seconds,
            actual_seconds=actual_seconds,
            planned_items=planned_items,
            completed_items=completed_items,
            skipped_items=skipped_items,
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
            )
            for day in days
        ],
        target_progress=target_progress,
        breakdown=breakdown,
        reflection=reflection,
        insights=insights,
    )

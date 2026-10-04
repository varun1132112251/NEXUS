from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from collections import defaultdict
import re
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
    AnalyticsDay,
    AnalyticsSummary,
    AnalyticsTotals,
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
    label = re.sub(r"\\s+", " ", (value or "Unlinked").strip())
    return label, label.casefold()


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

    schedules = list(
        db.scalars(
            select(ScheduleItem).where(
                ScheduleItem.user_id == user.id,
                ScheduleItem.scheduled_date >= start,
                ScheduleItem.scheduled_date <= end,
            )
        ).all()
    )

    range_start = datetime.combine(start, time.min, LOCAL_TZ).astimezone(UTC)
    range_end = datetime.combine(end, time.max, LOCAL_TZ).astimezone(UTC)

    sessions = list(
        db.scalars(
            select(TimeSession).where(
                TimeSession.user_id == user.id,
                TimeSession.status == "completed",
                TimeSession.started_at < range_end,
                TimeSession.ended_at.is_not(None),
                TimeSession.ended_at >= range_start,
            )
        ).all()
    )

    activities = list(
        db.scalars(
            select(ActivityRecord).where(
                ActivityRecord.user_id == user.id,
                ActivityRecord.recorded_at >= range_start,
                ActivityRecord.recorded_at <= range_end,
            )
        ).all()
    )

    diaries = list(
        db.scalars(
            select(DiaryEntry).where(
                DiaryEntry.user_id == user.id,
                DiaryEntry.entry_date >= start,
                DiaryEntry.entry_date <= end,
            )
        ).all()
    )

    planned_by_day = {day: 0 for day in (start.fromordinal(n) for n in range(start.toordinal(), end.toordinal() + 1))}
    actual_by_day = {day: 0 for day in planned_by_day}
    planned_items_by_day = {day: 0 for day in planned_by_day}
    completed_items_by_day = {day: 0 for day in planned_by_day}
    activity_by_day = {day: 0 for day in planned_by_day}

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
    completed_items = sum(1 for item in schedules if item.status == "completed")
    skipped_items = sum(1 for item in schedules if item.status == "skipped")
    planned_seconds = sum(planned_by_day.values())
    actual_seconds = sum(actual_by_day.values())

    targets = list(
        db.scalars(
            select(Target).where(
                Target.user_id == user.id,
                Target.month >= start.replace(day=1),
                Target.month <= end.replace(day=1),
            ).order_by(Target.month, Target.created_at)
        ).all()
    )

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
        target_progress.append(
            TargetProgress(
                id=str(target.id),
                title=target.title,
                month=target.month,
                target_value=target.target_value,
                current_value=target.current_value,
                progress_percent=percent,
                status=target.status,
            )
        )

    daily = [
        AnalyticsDay(
            date=day,
            planned_seconds=planned_by_day[day],
            actual_seconds=actual_by_day[day],
            planned_items=planned_items_by_day[day],
            completed_items=completed_items_by_day[day],
            activity_count=activity_by_day[day],
        )
        for day in sorted(planned_by_day)
    ]

    completion_rate = round((completed_items / planned_items) * 100, 2) if planned_items else 0.0

    breakdown = [
        {
            "key": key,
            "label": value["label"] or key,
            "seconds": value["seconds"],
            "session_count": value["session_count"],
            "activity_count": value["activity_count"],
            "metric_total": value["metric_total"],
        }
        for key, value in sorted(breakdown_map.items(), key=lambda item: item[1]["seconds"], reverse=True)
    ]

    return AnalyticsSummary(
        start_date=start,
        end_date=end,
        totals=AnalyticsTotals(
            planned_seconds=planned_seconds,
            actual_seconds=actual_seconds,
            planned_items=planned_items,
            completed_items=completed_items,
            skipped_items=skipped_items,
            schedule_completion_rate=completion_rate,
            session_count=len(sessions),
            activity_count=len(activities),
            diary_days=len(diaries),
        ),
        daily=daily,
        target_progress=target_progress,
        breakdown=breakdown,
    )

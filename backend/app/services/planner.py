"""Shared timezone and conflict rules for planner wall-clock dates."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.schedule import ScheduleItem
from app.models.user import User
from app.models.user_profile import UserProfile


def user_timezone(db: Session, user_id) -> ZoneInfo:
    profile = db.scalar(select(UserProfile).where(UserProfile.user_id == user_id))
    name = profile.timezone if profile is not None else None
    if not name:
        raise HTTPException(422, "Your profile timezone is missing. Set a valid IANA timezone before using planner analytics.")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise HTTPException(422, "Your profile timezone is not a valid IANA timezone.") from exc


def lock_user_schedule(db: Session, user_id) -> None:
    """Serialize per-user schedule writes so concurrent checks see committed blocks."""
    if db.scalar(select(User.id).where(User.id == user_id).with_for_update()) is None:
        raise HTTPException(404, "User not found.")


def localize_planner_datetime(value: datetime, timezone: ZoneInfo) -> datetime:
    """Interpret naive values as profile-local wall time; store all instants in UTC.

    Ambiguous and nonexistent local times must be resubmitted with an explicit
    UTC offset. This prevents DST transitions from silently shifting a block.
    """
    if value.tzinfo is not None and value.utcoffset() is not None:
        return value.astimezone(timezone).astimezone(UTC)

    first = value.replace(tzinfo=timezone, fold=0)
    second = value.replace(tzinfo=timezone, fold=1)
    first_roundtrip = first.astimezone(UTC).astimezone(timezone).replace(tzinfo=None)
    second_roundtrip = second.astimezone(UTC).astimezone(timezone).replace(tzinfo=None)
    if first_roundtrip != value or second_roundtrip != value:
        raise HTTPException(422, "This local time does not exist in your profile timezone; choose another time.")
    if first.utcoffset() != second.utcoffset():
        raise HTTPException(422, "This local time occurs twice in your profile timezone; provide an explicit UTC offset.")
    return first.astimezone(UTC)


def normalize_planner_interval(start_at: datetime, end_at: datetime, scheduled_date: date, timezone: ZoneInfo):
    start_utc = localize_planner_datetime(start_at, timezone)
    end_utc = localize_planner_datetime(end_at, timezone)
    if end_utc <= start_utc:
        raise HTTPException(422, "end_at must be after start_at.")
    if start_utc.astimezone(timezone).date() != scheduled_date or end_utc.astimezone(timezone).date() != scheduled_date:
        raise HTTPException(422, "start_at and end_at must fall on scheduled_date in your profile timezone.")
    return start_utc, end_utc


def schedule_conflicts(db: Session, *, user_id, start_at: datetime, end_at: datetime, exclude_id=None):
    query = select(ScheduleItem).where(
        ScheduleItem.user_id == user_id,
        ScheduleItem.deleted_at.is_(None),
        ScheduleItem.status.not_in(("skipped", "cancelled")),
        ScheduleItem.start_at < end_at,
        ScheduleItem.end_at > start_at,
    )
    if exclude_id is not None:
        query = query.where(ScheduleItem.id != exclude_id)
    rows = list(db.scalars(query.order_by(ScheduleItem.start_at, ScheduleItem.id)).all())
    return [{
        "id": str(row.id), "title": row.title, "scheduled_date": row.scheduled_date.isoformat(),
        "start_at": row.start_at.isoformat(), "end_at": row.end_at.isoformat(), "status": row.status,
    } for row in rows]


def reject_schedule_conflict(conflicts, allow_conflict: bool) -> None:
    if conflicts and not allow_conflict:
        raise HTTPException(status_code=409, detail={
            "message": "This block overlaps another scheduled block.",
            "conflicts": conflicts,
            "override": "Retry with allow_conflict=true to keep both blocks.",
        })

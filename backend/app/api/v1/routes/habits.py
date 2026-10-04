from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import get_current_user
from app.db.session import get_db
from app.models.activity_record import ActivityRecord
from app.models.habit import Habit
from app.models.schedule import ScheduleItem
from app.models.time_session import TimeSession
from app.models.user import User
from app.schemas.habit import HabitCreate, HabitRead, HabitStatsRead, HabitUpdate

router = APIRouter(prefix="/habits", tags=["habits"])
LOCAL_TZ = __import__("zoneinfo").ZoneInfo("Asia/Kolkata")


def owned(db: Session, habit_id, user_id):
    habit = db.scalar(select(Habit).where(Habit.id == habit_id, Habit.user_id == user_id))
    if not habit:
        raise HTTPException(404, "Habit not found.")
    return habit


def local_day(dt: datetime) -> date:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(LOCAL_TZ).date()


def consecutive_streak(days: set[date], anchor: date | None = None) -> int:
    if not days:
        return 0
    cursor = anchor or max(days)
    if cursor not in days:
        cursor = max((day for day in days if day <= cursor), default=None)
    if cursor is None:
        return 0
    streak = 0
    while cursor in days:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def scheduled_streak(days: set[date], completed: set[date], anchor: date) -> int:
    ordered = sorted(day for day in days if day <= anchor)
    if not ordered:
        return 0
    index = len(ordered) - 1
    while index >= 0 and ordered[index] not in completed:
        index -= 1
    if index < 0:
        return 0
    streak = 0
    while index >= 0 and ordered[index] in completed:
        streak += 1
        index -= 1
    return streak

def best_calendar_streak(days: set[date]) -> int:
    best = current = 0
    previous = None
    for day in sorted(days):
        if previous is not None and (day - previous).days == 1:
            current += 1
        else:
            current = 1
        best = max(best, current)
        previous = day
    return best

def expected_days(habit: Habit, start: date, end: date, scheduled: set[date]) -> set[date]:
    if scheduled:
        return scheduled
    if habit.frequency.lower() == "daily":
        return {start + timedelta(days=i) for i in range((end - start).days + 1)}
    if habit.frequency.lower() == "weekly":
        return {
            start + timedelta(days=i)
            for i in range((end - start).days + 1)
            if (start + timedelta(days=i)).weekday() == start.weekday()
        }
    return set()


@router.post("", response_model=HabitRead, status_code=status.HTTP_201_CREATED)
def create(payload: HabitCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    x = Habit(user_id=user.id, **payload.model_dump())
    db.add(x)
    db.commit()
    db.refresh(x)
    return x


@router.get("", response_model=list[HabitRead])
def list_all(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return list(db.scalars(select(Habit).where(Habit.user_id == user.id).order_by(Habit.active.desc(), Habit.name)).all())


@router.get("/stats", response_model=list[HabitStatsRead])
def stats(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    end = end_date or datetime.now(LOCAL_TZ).date()
    start = start_date or (end - timedelta(days=29))
    if end < start:
        raise HTTPException(422, "end_date must be on or after start_date.")

    habits = list(db.scalars(select(Habit).where(Habit.user_id == user.id)).all())
    schedules = list(db.scalars(select(ScheduleItem).where(
        ScheduleItem.user_id == user.id,
        ScheduleItem.habit_id.is_not(None),
        ScheduleItem.scheduled_date >= start,
        ScheduleItem.scheduled_date <= end,
    )).all())
    sessions = list(db.scalars(select(TimeSession).where(
        TimeSession.user_id == user.id,
        TimeSession.habit_id.is_not(None),
        TimeSession.status == "completed",
        TimeSession.started_at < datetime.combine(end + timedelta(days=1), datetime.min.time(), LOCAL_TZ),
    )).all())
    activities = list(db.scalars(select(ActivityRecord).where(
        ActivityRecord.user_id == user.id,
        ActivityRecord.habit_id.is_not(None),
        ActivityRecord.recorded_at >= datetime.combine(start, datetime.min.time(), LOCAL_TZ),
        ActivityRecord.recorded_at < datetime.combine(end + timedelta(days=1), datetime.min.time(), LOCAL_TZ),
    )).all())

    schedule_by_habit: dict[UUID, set[date]] = {}
    completed_by_habit: dict[UUID, set[date]] = {}
    focused_by_habit: dict[UUID, int] = {}

    for item in schedules:
        schedule_by_habit.setdefault(item.habit_id, set()).add(item.scheduled_date)
        if item.status == "completed":
            completed_by_habit.setdefault(item.habit_id, set()).add(item.scheduled_date)

    for session in sessions:
        day = local_day(session.started_at)
        if start <= day <= end:
            completed_by_habit.setdefault(session.habit_id, set()).add(day)
            focused_by_habit[session.habit_id] = focused_by_habit.get(session.habit_id, 0) + (session.duration_seconds or 0)

    for activity in activities:
        day = local_day(activity.recorded_at)
        if start <= day <= end:
            completed_by_habit.setdefault(activity.habit_id, set()).add(day)

    result = []
    for habit in habits:
        scheduled_days = schedule_by_habit.get(habit.id, set())
        expected = expected_days(habit, start, end, scheduled_days)
        completed = completed_by_habit.get(habit.id, set()) & set(
            start + timedelta(days=i) for i in range((end - start).days + 1)
        )
        completed_expected = completed & expected if expected else completed
        consistency = round((len(completed_expected) / len(expected)) * 100, 2) if expected else 0.0
        if scheduled_days:
            current = scheduled_streak(expected, completed_expected, end)
            best = max(
                (scheduled_streak(expected, completed_expected, day) for day in sorted(expected)),
                default=0,
            )
        else:
            current = consecutive_streak(completed_expected, end)
            best = best_calendar_streak(completed_expected)
        result.append(HabitStatsRead(
            habit_id=habit.id,
            expected_count=len(expected),
            completed_count=len(completed_expected),
            consistency_percent=consistency,
            current_streak=current,
            best_streak=best,
            focused_seconds=focused_by_habit.get(habit.id, 0),
            completed_days=len(completed_expected),
            last_completed_date=max(completed_expected) if completed_expected else None,
        ))
    return result


@router.patch("/{habit_id}", response_model=HabitRead)
def update(habit_id: UUID, payload: HabitUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    x = owned(db, habit_id, user.id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(x, k, v)
    db.commit()
    db.refresh(x)
    return x


@router.delete("/{habit_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(habit_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    x = owned(db, habit_id, user.id)
    db.delete(x)
    db.commit()

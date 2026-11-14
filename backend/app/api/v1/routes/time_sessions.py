from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import get_current_user
from app.db.session import get_db
from app.models.habit import Habit
from app.models.project import Project
from app.models.schedule import ScheduleItem
from app.models.task import Task
from app.models.target import Target
from app.models.time_session import TimeSession
from app.models.time_session_segment import TimeSessionSegment
from app.models.activity_session import ActivitySession
from app.models.user import User
from app.schemas.time_session import TimeSessionRead, TimeSessionStart

router = APIRouter(prefix="/time-sessions", tags=["time-sessions"])


def owned(db: Session, model, item_id: UUID, user_id: UUID, *, lock: bool = False):
    query = select(model).where(model.id == item_id, model.user_id == user_id)
    if lock:
        query = query.with_for_update()
    item = db.scalar(query)
    if item is None:
        raise HTTPException(status_code=404, detail=f"{model.__name__} not found.")
    return item


def validate_links(db: Session, payload: TimeSessionStart, user_id: UUID):
    schedule = None
    if payload.schedule_item_id is not None:
        schedule = owned(db, ScheduleItem, payload.schedule_item_id, user_id)
        if schedule.deleted_at is not None:
            raise HTTPException(status_code=404, detail="ScheduleItem not found.")
    if payload.task_id is not None:
        owned(db, Task, payload.task_id, user_id)
    if payload.habit_id is not None:
        owned(db, Habit, payload.habit_id, user_id)
    if payload.project_id is not None:
        owned(db, Project, payload.project_id, user_id)
    if payload.target_id is not None:
        owned(db, Target, payload.target_id, user_id)
    return schedule


def running_session(db: Session, user_id: UUID):
    return db.scalar(select(TimeSession).where(TimeSession.user_id == user_id, TimeSession.status.in_(("running", "paused"))).order_by(TimeSession.started_at.desc()))


def session_read(db: Session, session: TimeSession) -> TimeSessionRead:
    now = datetime.now(UTC)
    segments = db.scalars(select(TimeSessionSegment).where(TimeSessionSegment.time_session_id == session.id, TimeSessionSegment.user_id == session.user_id)).all()
    elapsed = sum(max(0, int(((segment.ended_at or now) - segment.started_at).total_seconds())) for segment in segments)
    return TimeSessionRead.model_validate(session, from_attributes=True).model_copy(update={"elapsed_seconds": elapsed})


@router.post("/start", response_model=TimeSessionRead, status_code=status.HTTP_201_CREATED)
def start(
    payload: TimeSessionStart,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if running_session(db, user.id) is not None:
        raise HTTPException(status_code=409, detail="A time session is already running.")

    schedule = validate_links(db, payload, user.id)
    session_data = payload.model_dump()
    if schedule is not None:
        session_data["task_id"] = session_data["task_id"] or schedule.task_id
        session_data["habit_id"] = session_data["habit_id"] or schedule.habit_id
        session_data["project_id"] = session_data["project_id"] or schedule.project_id
        session_data["target_id"] = session_data["target_id"] or schedule.target_id

    session = TimeSession(
        user_id=user.id,
        started_at=datetime.now(UTC),
        status="running",
        **session_data,
    )
    db.add(session)
    try:
        db.flush()
        db.add(TimeSessionSegment(time_session_id=session.id, user_id=user.id, started_at=session.started_at))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # The partial unique index is the final concurrency-safe guard. This
        # handles the race where two start requests both passed the read check.
        raise HTTPException(
            status_code=409,
            detail="A time session is already running.",
        ) from exc
    db.refresh(session)
    return session_read(db, session)


@router.get("/current", response_model=TimeSessionRead | None)
def current(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    session = running_session(db, user.id)
    return session_read(db, session) if session else None


@router.post("/{session_id}/pause", response_model=TimeSessionRead)
def pause(session_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    session = owned(db, TimeSession, session_id, user.id, lock=True)
    if session.status != "running":
        raise HTTPException(status_code=409, detail="Only a running session can be paused.")
    now = datetime.now(UTC)
    segment = db.scalar(select(TimeSessionSegment).where(TimeSessionSegment.time_session_id == session.id, TimeSessionSegment.user_id == user.id, TimeSessionSegment.ended_at.is_(None)).with_for_update())
    if segment is None:
        raise HTTPException(status_code=409, detail="Running session has no open segment.")
    if now <= segment.started_at:
        now = segment.started_at.replace(microsecond=0) + timedelta(seconds=1)
    segment.ended_at = now
    session.duration_seconds = sum(int((item.ended_at - item.started_at).total_seconds()) for item in db.scalars(select(TimeSessionSegment).where(TimeSessionSegment.time_session_id == session.id, TimeSessionSegment.user_id == user.id)).all())
    session.status = "paused"
    db.commit()
    db.refresh(session)
    return session_read(db, session)


@router.post("/{session_id}/resume", response_model=TimeSessionRead)
def resume(session_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    session = owned(db, TimeSession, session_id, user.id, lock=True)
    if session.status != "paused":
        raise HTTPException(status_code=409, detail="Only a paused session can be resumed.")
    current = running_session(db, user.id)
    if current is not None and current.id != session.id:
        raise HTTPException(status_code=409, detail="Another time session is active.")
    session.status = "running"
    session.duration_seconds = None
    db.add(TimeSessionSegment(time_session_id=session.id, user_id=user.id, started_at=datetime.now(UTC)))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Another time session is active.") from exc
    db.refresh(session)
    return session_read(db, session)


@router.post("/{session_id}/stop", response_model=TimeSessionRead)
def stop(
    session_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    session = owned(db, TimeSession, session_id, user.id, lock=True)
    if session.status not in {"running", "paused"}:
        raise HTTPException(status_code=409, detail="Time session is already stopped.")

    ended_at = datetime.now(UTC)
    if session.status == "running":
        segment = db.scalar(select(TimeSessionSegment).where(TimeSessionSegment.time_session_id == session.id, TimeSessionSegment.user_id == user.id, TimeSessionSegment.ended_at.is_(None)).with_for_update())
        if segment is None:
            raise HTTPException(status_code=409, detail="Running session has no open segment.")
        segment.ended_at = ended_at
    segments = db.scalars(select(TimeSessionSegment).where(TimeSessionSegment.time_session_id == session.id, TimeSessionSegment.user_id == user.id)).all()
    duration = sum(max(0, int((segment.ended_at - segment.started_at).total_seconds())) for segment in segments if segment.ended_at is not None)
    session.ended_at = ended_at
    session.duration_seconds = duration
    session.status = "completed"

    # Stopping a timer records actual work without deciding schedule completion.
    # Mark the linked block partial only when it is still planned and real time was recorded.
    if session.schedule_item_id is not None:
        schedule = db.scalar(select(ScheduleItem).where(
            ScheduleItem.id == session.schedule_item_id,
            ScheduleItem.user_id == user.id,
        ).with_for_update())
        if schedule is not None and schedule.deleted_at is None and schedule.status == "planned" and duration > 0:
            schedule.status = "partial"

    reviewed = db.scalar(select(ActivitySession).where(ActivitySession.time_session_id == session.id, ActivitySession.user_id == user.id))
    if reviewed is None:
        db.add(ActivitySession(
            user_id=user.id, time_session_id=session.id, schedule_item_id=session.schedule_item_id,
            task_id=session.task_id, habit_id=session.habit_id, project_id=session.project_id,
            target_id=session.target_id, title=session.title, notes=session.notes,
            started_at=session.started_at, ended_at=ended_at, duration_seconds=duration,
            confidence=1.0, status="draft", source_kind="stopwatch",
        ))

    db.commit()
    db.refresh(session)
    return session_read(db, session)


@router.get("", response_model=list[TimeSessionRead])
def history(
    habit_id: UUID | None = None,
    project_id: UUID | None = None,
    task_id: UUID | None = None,
    schedule_item_id: UUID | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = select(TimeSession).where(
        TimeSession.user_id == user.id,
        TimeSession.status == "completed",
    )
    if habit_id is not None:
        query = query.where(TimeSession.habit_id == habit_id)
    if project_id is not None:
        query = query.where(TimeSession.project_id == project_id)
    if task_id is not None:
        query = query.where(TimeSession.task_id == task_id)
    if schedule_item_id is not None:
        query = query.where(TimeSession.schedule_item_id == schedule_item_id)
    query = query.order_by(TimeSession.started_at.desc())
    return [session_read(db, item) for item in db.scalars(query).all()]

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import get_current_user
from app.db.session import get_db
from app.models.habit import Habit
from app.models.project import Project
from app.models.schedule import ScheduleItem
from app.models.task import Task
from app.models.target import Target
from app.models.target import Target
from app.models.time_session import TimeSession
from app.models.user import User
from app.schemas.time_session import TimeSessionRead, TimeSessionStart

router = APIRouter(prefix="/time-sessions", tags=["time-sessions"])


def owned(db: Session, model, item_id: UUID, user_id: UUID):
    item = db.scalar(select(model).where(model.id == item_id, model.user_id == user_id))
    if item is None:
        raise HTTPException(status_code=404, detail=f"{model.__name__} not found.")
    return item


def validate_links(db: Session, payload: TimeSessionStart, user_id: UUID):
    schedule = None
    if payload.schedule_item_id is not None:
        schedule = owned(db, ScheduleItem, payload.schedule_item_id, user_id)
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
    return db.scalar(
        select(TimeSession)
        .where(TimeSession.user_id == user_id, TimeSession.status == "running")
        .order_by(TimeSession.started_at.desc())
    )


@router.post("/start", response_model=TimeSessionRead, status_code=status.HTTP_201_CREATED)
def start(
    payload: TimeSessionStart,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if running_session(db, user.id) is not None:
        raise HTTPException(status_code=409, detail="A time session is already running.")

    schedule = validate_links(db, payload, user.id)
    if schedule is not None:
        if payload.task_id is None:
            payload.task_id = schedule.task_id
        if payload.habit_id is None:
            payload.habit_id = schedule.habit_id
        if payload.project_id is None:
            payload.project_id = schedule.project_id
        if payload.target_id is None:
            payload.target_id = schedule.target_id
        if payload.target_id is None:
            payload.target_id = schedule.target_id

    session = TimeSession(
        user_id=user.id,
        started_at=datetime.now(UTC),
        status="running",
        **payload.model_dump(),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.get("/current", response_model=TimeSessionRead | None)
def current(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return running_session(db, user.id)


@router.post("/{session_id}/stop", response_model=TimeSessionRead)
def stop(
    session_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    session = owned(db, TimeSession, session_id, user.id)
    if session.status != "running":
        raise HTTPException(status_code=409, detail="Time session is already stopped.")

    ended_at = datetime.now(UTC)
    duration = max(0, int((ended_at - session.started_at).total_seconds()))
    session.ended_at = ended_at
    session.duration_seconds = duration
    session.status = "completed"

    db.commit()
    db.refresh(session)
    return session


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
    return list(db.scalars(query).all())

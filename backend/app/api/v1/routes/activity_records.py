from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import get_current_user
from app.db.session import get_db
from app.models.activity_record import ActivityRecord
from app.models.habit import Habit
from app.models.project import Project
from app.models.task import Task
from app.models.target import Target
from app.models.time_session import TimeSession
from app.models.user import User
from app.schemas.activity_record import ActivityRecordCreate, ActivityRecordRead

router = APIRouter(prefix="/activity-records", tags=["activity-records"])


def owned(db: Session, model, item_id: UUID, user_id: UUID):
    item = db.scalar(select(model).where(model.id == item_id, model.user_id == user_id))
    if item is None:
        raise HTTPException(status_code=404, detail=f"{model.__name__} not found.")
    return item


def validate_links(db: Session, payload: ActivityRecordCreate, user_id: UUID):
    if payload.time_session_id is not None:
        owned(db, TimeSession, payload.time_session_id, user_id)
    if payload.task_id is not None:
        owned(db, Task, payload.task_id, user_id)
    if payload.habit_id is not None:
        owned(db, Habit, payload.habit_id, user_id)
    if payload.project_id is not None:
        owned(db, Project, payload.project_id, user_id)
    if payload.target_id is not None:
        owned(db, Target, payload.target_id, user_id)


@router.post("", response_model=ActivityRecordRead, status_code=status.HTTP_201_CREATED)
def create(
    payload: ActivityRecordCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    validate_links(db, payload, user.id)
    item = ActivityRecord(user_id=user.id, **payload.model_dump(exclude_none=True))
    db.add(item)
    if payload.target_id is not None and payload.contribution_value is not None:
        target = owned(db, Target, payload.target_id, user.id)
        target.current_value += payload.contribution_value
    db.commit()
    db.refresh(item)
    return item


@router.get("", response_model=list[ActivityRecordRead])
def list_records(
    activity_type: str | None = Query(default=None),
    habit_id: UUID | None = None,
    project_id: UUID | None = None,
    task_id: UUID | None = None,
    time_session_id: UUID | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = select(ActivityRecord).where(ActivityRecord.user_id == user.id)
    if activity_type is not None:
        query = query.where(ActivityRecord.activity_type == activity_type)
    if habit_id is not None:
        query = query.where(ActivityRecord.habit_id == habit_id)
    if project_id is not None:
        query = query.where(ActivityRecord.project_id == project_id)
    if task_id is not None:
        query = query.where(ActivityRecord.task_id == task_id)
    if time_session_id is not None:
        query = query.where(ActivityRecord.time_session_id == time_session_id)
    if target_id is not None:
        query = query.where(ActivityRecord.target_id == target_id)
    query = query.order_by(ActivityRecord.recorded_at.desc())
    return list(db.scalars(query).all())


@router.get("/{record_id}", response_model=ActivityRecordRead)
def read(
    record_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return owned(db, ActivityRecord, record_id, user.id)

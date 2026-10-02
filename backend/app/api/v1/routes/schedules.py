from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import get_current_user
from app.db.session import get_db
from app.models.habit import Habit
from app.models.project import Project
from app.models.schedule import ScheduleItem
from app.models.task import Task
from app.models.user import User
from app.schemas.schedule import ScheduleItemCreate, ScheduleItemRead, ScheduleItemUpdate

router = APIRouter(prefix="/schedule", tags=["schedule"])


def owned(db: Session, model, item_id: UUID, user_id: UUID):
    item = db.scalar(select(model).where(model.id == item_id, model.user_id == user_id))
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


@router.post("", response_model=ScheduleItemRead, status_code=status.HTTP_201_CREATED)
def create(
    payload: ScheduleItemCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    validate_links(db, payload, user.id)
    item = ScheduleItem(user_id=user.id, **payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("", response_model=list[ScheduleItemRead])
def list_schedule(
    scheduled_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = select(ScheduleItem).where(ScheduleItem.user_id == user.id)
    if scheduled_date is not None:
        query = query.where(ScheduleItem.scheduled_date == scheduled_date)
    query = query.order_by(ScheduleItem.scheduled_date, ScheduleItem.start_at)
    return list(db.scalars(query).all())


@router.patch("/{schedule_id}", response_model=ScheduleItemRead)
def update(
    schedule_id: UUID,
    payload: ScheduleItemUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = owned(db, ScheduleItem, schedule_id, user.id)
    validate_links(db, payload, user.id)

    merged = {
        "scheduled_date": payload.scheduled_date if payload.scheduled_date is not None else item.scheduled_date,
        "start_at": payload.start_at if payload.start_at is not None else item.start_at,
        "end_at": payload.end_at if payload.end_at is not None else item.end_at,
    }
    if merged["end_at"] <= merged["start_at"]:
        raise HTTPException(status_code=422, detail="end_at must be after start_at.")
    if merged["start_at"].date() != merged["scheduled_date"] or merged["end_at"].date() != merged["scheduled_date"]:
        raise HTTPException(status_code=422, detail="Schedule times must match scheduled_date.")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)

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
    db.delete(item)
    db.commit()

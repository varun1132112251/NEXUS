from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import get_current_user
from app.db.session import get_db
from app.models.routine_template import RoutineTemplate
from app.models.user import User
from app.models.habit import Habit
from app.models.project import Project
from app.models.task import Task
from app.models.target import Target
from app.models.schedule import ScheduleItem
from app.schemas.routine_template import RoutineGenerateRead, RoutineTemplateCreate, RoutineTemplateRead, RoutineTemplateUpdate
from app.services.planner import (
    localize_planner_datetime, reject_schedule_conflict, schedule_conflicts,
    lock_user_schedule, user_timezone,
)

router = APIRouter(prefix="/routines", tags=["routines"])


def owned(db: Session, model, item_id: UUID, user_id: UUID):
    item = db.scalar(select(model).where(model.id == item_id, model.user_id == user_id))
    if item is None:
        raise HTTPException(status_code=404, detail=f"{model.__name__} not found.")
    return item


def validate_links(db: Session, payload, user_id: UUID):
    for model, field in ((Habit, "habit_id"), (Task, "task_id"), (Project, "project_id"), (Target, "target_id")):
        item_id = getattr(payload, field, None)
        if item_id is not None:
            owned(db, model, item_id, user_id)


@router.post("", response_model=RoutineTemplateRead, status_code=status.HTTP_201_CREATED)
def create(payload: RoutineTemplateCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    validate_links(db, payload, user.id)
    item = RoutineTemplate(user_id=user.id, **payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("", response_model=list[RoutineTemplateRead])
def list_routines(include_inactive: bool = False, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = select(RoutineTemplate).where(RoutineTemplate.user_id == user.id)
    if not include_inactive:
        query = query.where(RoutineTemplate.active.is_(True))
    query = query.order_by(RoutineTemplate.start_time)
    return list(db.scalars(query).all())


@router.patch("/{routine_id}", response_model=RoutineTemplateRead)
def update(routine_id: UUID, payload: RoutineTemplateUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = owned(db, RoutineTemplate, routine_id, user.id)
    validate_links(db, payload, user.id)
    values = payload.model_dump(exclude_unset=True)
    for key, value in values.items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{routine_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(routine_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = owned(db, RoutineTemplate, routine_id, user.id)
    # Deactivation preserves source identity referenced by generated occurrences.
    item.active = False
    db.commit()


@router.post("/generate/{target_date}", response_model=RoutineGenerateRead)
def generate(target_date: date, db: Session = Depends(get_db), user: User = Depends(get_current_user), allow_conflict: bool = False):
    lock_user_schedule(db, user.id)
    timezone = user_timezone(db, user.id)
    weekday = target_date.weekday()
    templates = list(db.scalars(
        select(RoutineTemplate).where(
            RoutineTemplate.user_id == user.id,
            RoutineTemplate.active.is_(True),
        ).order_by(RoutineTemplate.start_time)
    ).all())
    templates = [template for template in templates if weekday in template.weekdays]

    existing = list(db.scalars(
        select(ScheduleItem).where(
            ScheduleItem.user_id == user.id,
            ScheduleItem.scheduled_date == target_date,
        )
    ).all())
    existing_ids = {x.routine_template_id for x in existing if x.routine_template_id is not None}

    created = 0
    for template in templates:
        start_at = localize_planner_datetime(datetime.combine(target_date, template.start_time), timezone)
        end_at = localize_planner_datetime(datetime.combine(target_date, template.end_time), timezone)
        if template.id in existing_ids:
            continue
        conflicts = schedule_conflicts(db, user_id=user.id, start_at=start_at, end_at=end_at)
        reject_schedule_conflict(conflicts, allow_conflict)
        db.add(ScheduleItem(
            user_id=user.id,
            task_id=template.task_id,
            habit_id=template.habit_id,
            project_id=template.project_id,
            target_id=template.target_id,
            routine_template_id=template.id,
            title=template.title,
            notes=template.notes,
            scheduled_date=target_date,
            start_at=start_at,
            end_at=end_at,
            priority=template.priority,
            status="planned",
        ))
        db.flush()
        created += 1

    db.commit()
    return RoutineGenerateRead(date=target_date, created_count=created)

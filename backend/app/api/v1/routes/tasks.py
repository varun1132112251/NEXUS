from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import get_current_user
from app.db.session import get_db
from app.models.project import Project
from app.models.ambition_goal import AmbitionGoal
from app.models.target import Target
from app.models.task import Task
from app.models.task_status_event import TaskStatusEvent
from app.models.user import User
from app.services.planner import user_timezone
from app.schemas.task import TaskCreate, TaskRead, TaskStatusEventRead, TaskUpdate

router = APIRouter(prefix="/tasks", tags=["tasks"])

TASK_TRANSITIONS = {
    "planned": {"in_progress", "completed", "blocked", "cancelled"},
    "in_progress": {"planned", "completed", "blocked", "cancelled"},
    "blocked": {"planned", "in_progress", "cancelled"},
    "completed": {"planned"},
    "cancelled": {"planned"},
}


def owned(db: Session, task_id: UUID, user_id: UUID, *, include_deleted: bool = False) -> Task:
    query = select(Task).where(Task.id == task_id, Task.user_id == user_id).with_for_update()
    if not include_deleted:
        query = query.where(Task.deleted_at.is_(None))
    task = db.scalar(query)
    if task is None:
        raise HTTPException(404, "Task not found.")
    return task


def validate_links(db: Session, payload, user_id: UUID) -> None:
    for model, field in ((Project, "project_id"), (Target, "target_id"), (AmbitionGoal, "ambition_goal_id")):
        item_id = getattr(payload, field, None)
        if item_id is not None and db.scalar(select(model.id).where(model.id == item_id, model.user_id == user_id)) is None:
            raise HTTPException(404, f"{model.__name__} not found.")


@router.post("", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
def create(payload: TaskCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    validate_links(db, payload, user.id)
    item = Task(user_id=user.id, **payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("", response_model=list[TaskRead])
def list_all(
    status_filter: str | None = None,
    priority: int | None = None,
    project_id: UUID | None = None,
    ambition_goal_id: UUID | None = None,
    due_from: date | None = None,
    due_to: date | None = None,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    query = select(Task).where(Task.user_id == user.id, Task.deleted_at.is_(None))
    if status_filter is not None:
        if status_filter not in {"planned", "in_progress", "completed", "blocked", "cancelled"}:
            raise HTTPException(422, "Invalid task status filter.")
        query = query.where(Task.status == status_filter)
    if priority is not None:
        if priority < 1 or priority > 5:
            raise HTTPException(422, "Priority must be between 1 and 5.")
        query = query.where(Task.priority == priority)
    if project_id is not None:
        query = query.where(Task.project_id == project_id)
    if ambition_goal_id is not None:
        query = query.where(Task.ambition_goal_id == ambition_goal_id)
    if due_from is not None or due_to is not None:
        timezone = user_timezone(db, user.id)
        if due_from is not None:
            query = query.where(Task.due_at >= datetime.combine(due_from, time.min, timezone).astimezone(UTC))
        if due_to is not None:
            query = query.where(Task.due_at < datetime.combine(due_to + timedelta(days=1), time.min, timezone).astimezone(UTC))
    return list(db.scalars(query.order_by(Task.due_at.nulls_last(), Task.priority, Task.created_at)).all())


@router.get("/{task_id}/history", response_model=list[TaskStatusEventRead])
def history(task_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    owned(db, task_id, user.id, include_deleted=True)
    return list(db.scalars(select(TaskStatusEvent).where(
        TaskStatusEvent.task_id == task_id, TaskStatusEvent.user_id == user.id
    ).order_by(TaskStatusEvent.created_at, TaskStatusEvent.id)).all())


@router.patch("/{task_id}", response_model=TaskRead)
def update(task_id: UUID, payload: TaskUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = owned(db, task_id, user.id)
    validate_links(db, payload, user.id)
    values = payload.model_dump(exclude_unset=True)
    next_status = values.get("status")
    if next_status is not None and next_status != item.status and next_status not in TASK_TRANSITIONS[item.status]:
        raise HTTPException(409, f"Task cannot transition from {item.status} to {next_status}.")
    for field, value in values.items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(task_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = owned(db, task_id, user.id)
    # Keep task status history and historical planner/execution links intact.
    item.deleted_at = datetime.now(UTC)
    db.commit()

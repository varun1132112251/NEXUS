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

METRIC_KEYS = {
    "count": "count",
    "problems_solved": "problems_solved",
    "pages_read": "pages_read",
    "sessions_completed": "sessions_completed",
    "questions_solved": "questions_solved",
    "topics_revised": "topics_revised",
    "milestones_completed": "milestones_completed",
    "books_completed": "books_completed",
}

DETAIL_INT_KEYS = {"attempted", "mistakes", "words_learned", "questions_solved", "pages_read", "problems_solved", "sessions_completed", "topics_revised", "milestones_completed", "books_completed", "count"}
DETAIL_FLOAT_KEYS = {"accuracy"}

def validate_details(metric_type: str, details: dict, metric_value: int | None) -> None:
    expected_key = METRIC_KEYS.get(metric_type)
    if expected_key is None:
        raise HTTPException(status_code=422, detail=f"Unsupported activity metric '{metric_type}'.")

    if metric_value is not None:
        expected_value = details.get(expected_key)
        if expected_value != metric_value:
            raise HTTPException(
                status_code=422,
                detail=f"details.{expected_key} must equal metric_value.",
            )

    for key in DETAIL_INT_KEYS.intersection(details):
        value = details[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise HTTPException(status_code=422, detail=f"details.{key} must be a non-negative integer.")

    for key in DETAIL_FLOAT_KEYS.intersection(details):
        value = details[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= float(value) <= 100:
            raise HTTPException(status_code=422, detail=f"details.{key} must be between 0 and 100.")

    if metric_type == "problems_solved":
        attempted = details.get("attempted")
        solved = details.get("problems_solved")
        if attempted is not None and solved is not None and solved > attempted:
            raise HTTPException(status_code=422, detail="Solved problems cannot exceed attempted problems.")



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
        return owned(db, Target, payload.target_id, user_id)
    return None


@router.post("", response_model=ActivityRecordRead, status_code=status.HTTP_201_CREATED)
def create(
    payload: ActivityRecordCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    target = validate_links(db, payload, user.id)
    if payload.time_session_id is not None:
        existing = db.scalar(select(ActivityRecord).where(ActivityRecord.user_id == user.id, ActivityRecord.time_session_id == payload.time_session_id))
        if existing is not None:
            raise HTTPException(status_code=409, detail="This time session has already been reviewed.")
    metric_type = target.metric_type if target is not None else (payload.metric_type or payload.activity_type)
    validate_details(metric_type, payload.details, payload.metric_value)

    if target is not None:
        if payload.metric_value is None:
            raise HTTPException(status_code=422, detail=f"Enter a measured value for target metric '{target.metric_type}'.")
        target.current_value += payload.metric_value

    item_payload = payload.model_dump(exclude_none=True)
    item_payload.pop("metric_type", None)
    item = ActivityRecord(user_id=user.id, **item_payload)
    db.add(item)
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
    target_id: UUID | None = None,
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

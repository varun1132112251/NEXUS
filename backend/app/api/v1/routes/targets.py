from datetime import date
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.api.v1.routes.auth import get_current_user
from app.db.session import get_db
from app.models.target import Target
from app.models.ambition_goal import AmbitionGoal
from app.models.user import User
from app.schemas.target import TargetCreate, TargetRead, TargetUpdate
from app.services.ownership import ReferencedTargetError, unlink_owned_references

router = APIRouter(prefix="/targets", tags=["targets"])

EXPECTED_TARGET_REFERENCE_FK_SQLSTATES = {
    "fk_tasks_target_user": frozenset({"23503"}),
    "fk_schedule_items_target_user": frozenset({"23503"}),
    "fk_time_sessions_target_user": frozenset({"23503"}),
    # K6 creates this FK with ON DELETE RESTRICT (23001); model metadata uses
    # NO ACTION (23503), so recognize both deployed and metadata-created forms.
    "fk_activity_sessions_target_user": frozenset({"23001", "23503"}),
    "fk_activity_goal_contributions_target_user": frozenset({"23503"}),
}


def is_expected_target_reference_integrity_error(exc: IntegrityError) -> bool:
    """Match only PostgreSQL FK violations known to reference a target row."""
    original = exc.orig
    sqlstate = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    diagnostic = getattr(original, "diag", None)
    constraint_name = getattr(diagnostic, "constraint_name", None)
    return sqlstate in EXPECTED_TARGET_REFERENCE_FK_SQLSTATES.get(constraint_name, ())

def owned_target(db: Session, target_id: UUID, user_id: UUID) -> Target:
    target = db.scalar(select(Target).where(Target.id == target_id, Target.user_id == user_id))
    if target is None: raise HTTPException(status_code=404, detail="Target not found.")
    return target


def inferred_metric_type(title: str) -> str:
    text = title.lower()
    if "dsa" in text or "problem" in text:
        return "problems_solved"
    if "book" in text and ("read" in text or "reading" in text):
        return "books_completed"
    if "english" in text and "session" in text:
        return "sessions_completed"
    if "gate" in text and "revision" in text:
        return "topics_revised"
    if "gate" in text and "question" in text:
        return "questions_solved"
    if "nexus" in text and ("complete" in text or "v1" in text):
        return "milestones_completed"
    return "count"


@router.post("", response_model=TargetRead, status_code=status.HTTP_201_CREATED)
def create_target(payload: TargetCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Target:
    data = payload.model_dump()
    data.pop("period_start", None)
    goal_id = data.get("ambition_goal_id")
    if goal_id is not None and db.scalar(select(AmbitionGoal.id).where(AmbitionGoal.id == goal_id, AmbitionGoal.user_id == user.id)) is None:
        raise HTTPException(status_code=404, detail="Ambition goal not found.")
    if data["metric_type"] == "count":
        data["metric_type"] = inferred_metric_type(data["title"])
    target = Target(user_id=user.id, **data)
    db.add(target)
    db.commit()
    db.refresh(target)
    return target

@router.get("", response_model=list[TargetRead])
def list_targets(
    month: date | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Target]:
    query = select(Target).where(Target.user_id == user.id)
    if month is not None:
        query = query.where(Target.month == month)
    query = query.order_by(Target.month, Target.created_at)
    return list(db.scalars(query).all())

@router.patch("/{target_id}", response_model=TargetRead)
def update_target(target_id: UUID, payload: TargetUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Target:
    target = owned_target(db, target_id, user.id)
    values = payload.model_dump(exclude_unset=True)
    if values.get("period_start") is not None:
        values["month"] = values.pop("period_start")
    else:
        values.pop("period_start", None)
    if values.get("ambition_goal_id") is not None and db.scalar(select(AmbitionGoal.id).where(AmbitionGoal.id == values["ambition_goal_id"], AmbitionGoal.user_id == user.id)) is None:
        raise HTTPException(status_code=404, detail="Ambition goal not found.")
    for key, value in values.items(): setattr(target, key, value)
    db.commit(); db.refresh(target); return target

@router.delete(
    "/{target_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={409: {"description": "Target still has historical activity or contribution references."}},
)
def delete_target(target_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> None:
    target = owned_target(db, target_id, user.id)
    try:
        unlink_owned_references(db, Target, target.id, user.id)
    except ReferencedTargetError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.delete(target)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if is_expected_target_reference_integrity_error(exc):
            raise HTTPException(
                status_code=409,
                detail="Target is still referenced by historical records and cannot be deleted.",
            ) from exc
        raise

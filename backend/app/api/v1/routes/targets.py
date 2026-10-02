from datetime import date
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.v1.routes.auth import get_current_user
from app.db.session import get_db
from app.models.target import Target
from app.models.user import User
from app.schemas.target import TargetCreate, TargetRead, TargetUpdate

router = APIRouter(prefix="/targets", tags=["targets"])

def owned_target(db: Session, target_id: UUID, user_id: UUID) -> Target:
    target = db.scalar(select(Target).where(Target.id == target_id, Target.user_id == user_id))
    if target is None: raise HTTPException(status_code=404, detail="Target not found.")
    return target

@router.post("", response_model=TargetRead, status_code=status.HTTP_201_CREATED)
def create_target(payload: TargetCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Target:
    target = Target(user_id=user.id, **payload.model_dump())
    db.add(target); db.commit(); db.refresh(target); return target

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
    for key, value in payload.model_dump(exclude_unset=True).items(): setattr(target, key, value)
    db.commit(); db.refresh(target); return target

@router.delete("/{target_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_target(target_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> None:
    target = owned_target(db, target_id, user.id); db.delete(target); db.commit()

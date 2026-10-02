from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import get_current_user
from app.db.session import get_db
from app.models.diary import DiaryEntry
from app.models.user import User
from app.schemas.diary import DiaryCreate, DiaryRead, DiaryUpdate

router = APIRouter(prefix="/diary", tags=["diary"])


def owned_entry(db: Session, entry_id: UUID, user_id: UUID) -> DiaryEntry:
    entry = db.scalar(select(DiaryEntry).where(DiaryEntry.id == entry_id, DiaryEntry.user_id == user_id))
    if entry is None:
        raise HTTPException(status_code=404, detail="Diary entry not found.")
    return entry


@router.post("", response_model=DiaryRead, status_code=status.HTTP_201_CREATED)
def create_entry(
    payload: DiaryCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DiaryEntry:
    existing = db.scalar(
        select(DiaryEntry).where(
            DiaryEntry.user_id == user.id,
            DiaryEntry.entry_date == payload.entry_date,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="A diary entry already exists for this date.")
    entry = DiaryEntry(user_id=user.id, **payload.model_dump())
    db.add(entry)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A diary entry already exists for this date.") from None
    db.refresh(entry)
    return entry


@router.get("", response_model=list[DiaryRead])
def list_entries(
    entry_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DiaryEntry]:
    query = select(DiaryEntry).where(DiaryEntry.user_id == user.id)
    if entry_date is not None:
        query = query.where(DiaryEntry.entry_date == entry_date)
    query = query.order_by(DiaryEntry.entry_date.desc())
    return list(db.scalars(query).all())


@router.get("/{entry_id}", response_model=DiaryRead)
def read_entry(
    entry_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DiaryEntry:
    return owned_entry(db, entry_id, user.id)


@router.patch("/{entry_id}", response_model=DiaryRead)
def update_entry(
    entry_id: UUID,
    payload: DiaryUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DiaryEntry:
    entry = owned_entry(db, entry_id, user.id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(entry, key, value)
    db.commit()
    db.refresh(entry)
    return entry


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_entry(
    entry_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    entry = owned_entry(db, entry_id, user.id)
    db.delete(entry)
    db.commit()

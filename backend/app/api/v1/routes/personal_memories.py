from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import get_current_user
from app.db.session import get_db
from app.models.personal_memory import PersonalMemory
from app.models.user import User
from app.schemas.personal_memory import (
    MemoryCategory,
    PersonalMemoryCreate,
    PersonalMemoryRead,
    PersonalMemoryUpdate,
)

router = APIRouter(prefix="/memory", tags=["personal-memory"])


def owned_memory(db: Session, memory_id: UUID, user_id: UUID) -> PersonalMemory:
    memory = db.scalar(
        select(PersonalMemory).where(
            PersonalMemory.id == memory_id,
            PersonalMemory.user_id == user_id,
        )
    )
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found.")
    return memory


@router.post("", response_model=PersonalMemoryRead, status_code=status.HTTP_201_CREATED)
def create_memory(
    payload: PersonalMemoryCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PersonalMemory:
    if payload.supersedes_id is not None:
        previous = owned_memory(db, payload.supersedes_id, user.id)
        if previous.status != "active":
            raise HTTPException(status_code=409, detail="Only active memories can be superseded.")
        if previous.category != payload.category:
            raise HTTPException(status_code=422, detail="A replacement memory must use the same category.")
        previous.status = "superseded"

    memory = PersonalMemory(
        user_id=user.id,
        category=payload.category,
        title=payload.title,
        content=payload.content,
        source_kind="user_stated",
        confidence=1.0,
        importance=payload.importance,
        details=payload.details,
        source_reference=payload.source_reference,
        supersedes_id=payload.supersedes_id,
        expires_at=payload.expires_at,
    )
    db.add(memory)
    db.commit()
    db.refresh(memory)
    return memory


@router.get("", response_model=list[PersonalMemoryRead])
def list_memories(
    category: MemoryCategory | None = None,
    status_filter: str = Query(default="active", alias="status", pattern="^(active|superseded|archived|all)$"),
    search: str | None = Query(default=None, min_length=1, max_length=100),
    include_expired: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[PersonalMemory]:
    query = select(PersonalMemory).where(PersonalMemory.user_id == user.id)
    if category is not None:
        query = query.where(PersonalMemory.category == category)
    if status_filter != "all":
        query = query.where(PersonalMemory.status == status_filter)
    if not include_expired:
        query = query.where(
            or_(PersonalMemory.expires_at.is_(None), PersonalMemory.expires_at > datetime.now(UTC))
        )
    if search is not None:
        pattern = f"%{search}%"
        query = query.where(or_(PersonalMemory.title.ilike(pattern), PersonalMemory.content.ilike(pattern)))
    query = query.order_by(PersonalMemory.importance.desc(), PersonalMemory.updated_at.desc())
    return list(db.scalars(query).all())


@router.get("/{memory_id}", response_model=PersonalMemoryRead)
def read_memory(
    memory_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PersonalMemory:
    memory = owned_memory(db, memory_id, user.id)
    if memory.status == "archived":
        raise HTTPException(status_code=404, detail="Memory not found.")
    return memory


@router.patch("/{memory_id}", response_model=PersonalMemoryRead)
def update_memory(
    memory_id: UUID,
    payload: PersonalMemoryUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PersonalMemory:
    memory = owned_memory(db, memory_id, user.id)
    if memory.status != "active":
        raise HTTPException(status_code=409, detail="Only active memories can be updated.")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(memory, key, value)
    db.commit()
    db.refresh(memory)
    return memory


@router.post("/{memory_id}/archive", response_model=PersonalMemoryRead)
def archive_memory(
    memory_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PersonalMemory:
    memory = owned_memory(db, memory_id, user.id)
    if memory.status == "superseded":
        raise HTTPException(status_code=409, detail="Superseded memories cannot be archived.")
    memory.status = "archived"
    db.commit()
    db.refresh(memory)
    return memory

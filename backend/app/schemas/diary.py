from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DiaryCreate(BaseModel):
    entry_date: date
    accomplishments: str | None = None
    what_went_badly: str | None = None
    learned: str | None = None
    feelings: str | None = None
    distractions: str | None = None
    tomorrow_changes: str | None = None
    free_writing: str | None = None


class DiaryUpdate(BaseModel):
    accomplishments: str | None = None
    what_went_badly: str | None = None
    learned: str | None = None
    feelings: str | None = None
    distractions: str | None = None
    tomorrow_changes: str | None = None
    free_writing: str | None = None


class DiaryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    entry_date: date
    accomplishments: str | None
    what_went_badly: str | None
    learned: str | None
    feelings: str | None
    distractions: str | None
    tomorrow_changes: str | None
    free_writing: str | None
    created_at: datetime
    updated_at: datetime

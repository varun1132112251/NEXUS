from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TimeSessionStart(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    notes: str | None = None
    schedule_item_id: UUID | None = None
    task_id: UUID | None = None
    habit_id: UUID | None = None
    project_id: UUID | None = None


class TimeSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    user_id: UUID
    schedule_item_id: UUID | None
    task_id: UUID | None
    habit_id: UUID | None
    project_id: UUID | None
    title: str
    notes: str | None
    started_at: datetime
    ended_at: datetime | None
    duration_seconds: int | None
    status: str
    created_at: datetime
    updated_at: datetime

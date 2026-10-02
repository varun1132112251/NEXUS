from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ActivityRecordCreate(BaseModel):
    activity_type: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=255)
    details: dict = Field(default_factory=dict)
    notes: str | None = None
    recorded_at: datetime | None = None
    time_session_id: UUID | None = None
    task_id: UUID | None = None
    habit_id: UUID | None = None
    project_id: UUID | None = None


class ActivityRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    user_id: UUID
    time_session_id: UUID | None
    task_id: UUID | None
    habit_id: UUID | None
    project_id: UUID | None
    activity_type: str
    title: str
    details: dict
    notes: str | None
    recorded_at: datetime
    created_at: datetime
    updated_at: datetime

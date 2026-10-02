from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    project_id: UUID | None = None
    target_id: UUID | None = None
    priority: int = Field(default=3, ge=1, le=5)
    due_at: datetime | None = None

class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    project_id: UUID | None = None
    target_id: UUID | None = None
    status: str | None = Field(default=None, min_length=1, max_length=32)
    priority: int | None = Field(default=None, ge=1, le=5)
    due_at: datetime | None = None

class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    user_id: UUID
    project_id: UUID | None
    target_id: UUID | None
    title: str
    description: str | None
    status: str
    priority: int
    due_at: datetime | None
    created_at: datetime
    updated_at: datetime

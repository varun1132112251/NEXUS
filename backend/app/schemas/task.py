from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

TaskStatus = Literal["planned", "in_progress", "completed", "blocked", "cancelled"]

class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    project_id: UUID | None = None
    target_id: UUID | None = None
    ambition_goal_id: UUID | None = None
    priority: int = Field(default=3, ge=1, le=5)
    due_at: datetime | None = None

class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    project_id: UUID | None = None
    target_id: UUID | None = None
    ambition_goal_id: UUID | None = None
    status: TaskStatus | None = None
    priority: int | None = Field(default=None, ge=1, le=5)
    due_at: datetime | None = None

class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    user_id: UUID
    project_id: UUID | None
    target_id: UUID | None
    ambition_goal_id: UUID | None
    title: str
    description: str | None
    status: str
    priority: int
    due_at: datetime | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class TaskStatusEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    task_id: UUID
    previous_status: str | None
    new_status: str
    event_kind: str
    created_at: datetime

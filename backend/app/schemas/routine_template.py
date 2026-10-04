from datetime import date, datetime, time
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RoutineTemplateCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    notes: str | None = None
    weekday: int = Field(ge=0, le=6)
    start_time: time
    end_time: time
    habit_id: UUID | None = None
    task_id: UUID | None = None
    project_id: UUID | None = None
    target_id: UUID | None = None
    priority: int = Field(default=3, ge=1, le=5)
    active: bool = True

    @model_validator(mode="after")
    def validate_times(self):
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time.")
        return self


class RoutineTemplateUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    notes: str | None = None
    weekday: int | None = Field(default=None, ge=0, le=6)
    start_time: time | None = None
    end_time: time | None = None
    habit_id: UUID | None = None
    task_id: UUID | None = None
    project_id: UUID | None = None
    target_id: UUID | None = None
    priority: int | None = Field(default=None, ge=1, le=5)
    active: bool | None = None


class RoutineTemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    user_id: UUID
    habit_id: UUID | None
    task_id: UUID | None
    project_id: UUID | None
    target_id: UUID | None
    title: str
    notes: str | None
    weekday: int
    start_time: time
    end_time: time
    priority: int
    active: bool
    created_at: datetime
    updated_at: datetime


class RoutineGenerateRead(BaseModel):
    date: date
    created_count: int

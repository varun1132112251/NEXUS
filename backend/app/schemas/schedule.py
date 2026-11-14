from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

ScheduleStatus = Literal["planned", "partial", "completed", "skipped", "missed", "cancelled"]


class ScheduleItemCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    notes: str | None = None
    scheduled_date: date
    start_at: datetime
    end_at: datetime
    task_id: UUID | None = None
    habit_id: UUID | None = None
    project_id: UUID | None = None
    target_id: UUID | None = None
    routine_template_id: UUID | None = None
    ambition_goal_id: UUID | None = None
    priority: int = Field(default=3, ge=1, le=5)
    status: ScheduleStatus = "planned"

    @model_validator(mode="after")
    def validate_times(self):
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at.")
        return self


class ScheduleItemUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    notes: str | None = None
    scheduled_date: date | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    task_id: UUID | None = None
    habit_id: UUID | None = None
    project_id: UUID | None = None
    target_id: UUID | None = None
    routine_template_id: UUID | None = None
    ambition_goal_id: UUID | None = None
    priority: int | None = Field(default=None, ge=1, le=5)
    status: ScheduleStatus | None = None

    @model_validator(mode="after")
    def validate_times(self):
        values = self.model_dump(exclude_unset=True)
        start = values.get("start_at")
        end = values.get("end_at")
        scheduled_date = values.get("scheduled_date")
        if start is not None and end is not None and end <= start:
            raise ValueError("end_at must be after start_at.")
        return self


class ScheduleItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    user_id: UUID
    task_id: UUID | None
    habit_id: UUID | None
    project_id: UUID | None
    target_id: UUID | None
    routine_template_id: UUID | None
    ambition_goal_id: UUID | None
    title: str
    notes: str | None
    scheduled_date: date
    start_at: datetime
    end_at: datetime
    priority: int
    status: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class ScheduleStatusEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    schedule_item_id: UUID
    previous_status: str | None
    new_status: str
    event_kind: str
    created_at: datetime

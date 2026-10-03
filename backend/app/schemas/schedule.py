from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    priority: int = Field(default=3, ge=1, le=5)
    status: str = Field(default="planned", min_length=1, max_length=32)

    @model_validator(mode="after")
    def validate_times(self):
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at.")
        if self.start_at.date() != self.scheduled_date or self.end_at.date() != self.scheduled_date:
            raise ValueError("start_at and end_at must match scheduled_date.")
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
    priority: int | None = Field(default=None, ge=1, le=5)
    status: str | None = Field(default=None, min_length=1, max_length=32)

    @model_validator(mode="after")
    def validate_times(self):
        values = self.model_dump(exclude_unset=True)
        start = values.get("start_at")
        end = values.get("end_at")
        scheduled_date = values.get("scheduled_date")
        if start is not None and end is not None and end <= start:
            raise ValueError("end_at must be after start_at.")
        if scheduled_date is not None:
            if start is not None and start.date() != scheduled_date:
                raise ValueError("start_at must match scheduled_date.")
            if end is not None and end.date() != scheduled_date:
                raise ValueError("end_at must match scheduled_date.")
        return self


class ScheduleItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    user_id: UUID
    task_id: UUID | None
    habit_id: UUID | None
    project_id: UUID | None
    target_id: UUID | None
    title: str
    notes: str | None
    scheduled_date: date
    start_at: datetime
    end_at: datetime
    priority: int
    status: str
    created_at: datetime
    updated_at: datetime

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

MetricType = Literal[
    "count",
    "problems_solved",
    "pages_read",
    "sessions_completed",
    "questions_solved",
    "topics_revised",
    "milestones_completed",
    "books_completed",
    "time",
    "duration",
    "seconds",
    "distance",
    "weight",
    "currency",
    "percentage",
    "proficiency",
    "custom",
]


class TargetCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    month: date | None = None
    period_start: date | None = None
    metric_type: MetricType = "count"
    target_value: int | None = Field(default=None, ge=0)
    ambition_goal_id: UUID | None = None
    period_type: Literal["monthly", "weekly"] = "monthly"

    @model_validator(mode="after")
    def period_start_required(self):
        if self.month is None and self.period_start is None:
            raise ValueError("month or period_start is required")
        if self.month is not None and self.period_start is not None and self.month != self.period_start:
            raise ValueError("month and period_start must match when both are provided")
        if self.month is None:
            self.month = self.period_start
        return self


class TargetUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    metric_type: MetricType | None = None
    target_value: int | None = Field(default=None, ge=0)
    current_value: int | None = Field(default=None, ge=0)
    status: str | None = Field(default=None, min_length=1, max_length=32)
    ambition_goal_id: UUID | None = None
    period_type: Literal["monthly", "weekly"] | None = None
    period_start: date | None = None


class TargetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    user_id: UUID
    title: str
    description: str | None
    month: date
    period_start: date
    period_type: str
    ambition_goal_id: UUID | None
    metric_type: MetricType
    target_value: int | None
    current_value: int
    status: str
    created_at: datetime
    updated_at: datetime

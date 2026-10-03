from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

MetricType = Literal[
    "count",
    "problems_solved",
    "pages_read",
    "sessions_completed",
    "questions_solved",
    "topics_revised",
    "milestones_completed",
    "books_completed",
]


class TargetCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    month: date
    metric_type: MetricType = "count"
    target_value: int | None = Field(default=None, ge=0)


class TargetUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    metric_type: MetricType | None = None
    target_value: int | None = Field(default=None, ge=0)
    current_value: int | None = Field(default=None, ge=0)
    status: str | None = Field(default=None, min_length=1, max_length=32)


class TargetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    user_id: UUID
    title: str
    description: str | None
    month: date
    metric_type: MetricType
    target_value: int | None
    current_value: int
    status: str
    created_at: datetime
    updated_at: datetime

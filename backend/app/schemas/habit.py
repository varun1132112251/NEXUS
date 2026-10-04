from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.target import MetricType

class HabitCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    category: str = Field(default="general", min_length=1, max_length=64)
    frequency: str = Field(default="daily", min_length=1, max_length=32)
    metric_type: MetricType = "count"

class HabitUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    category: str | None = Field(default=None, min_length=1, max_length=64)
    frequency: str | None = Field(default=None, min_length=1, max_length=32)
    metric_type: MetricType | None = None
    active: bool | None = None

class HabitRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    user_id: UUID
    name: str
    description: str | None
    category: str
    frequency: str
    metric_type: MetricType
    active: bool
    created_at: datetime
    updated_at: datetime

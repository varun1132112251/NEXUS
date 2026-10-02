from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

class HabitCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    category: str = Field(default="general", min_length=1, max_length=64)
    frequency: str = Field(default="daily", min_length=1, max_length=32)

class HabitUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    category: str | None = Field(default=None, min_length=1, max_length=64)
    frequency: str | None = Field(default=None, min_length=1, max_length=32)
    active: bool | None = None

class HabitRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    user_id: UUID
    name: str
    description: str | None
    category: str
    frequency: str
    active: bool
    created_at: datetime
    updated_at: datetime

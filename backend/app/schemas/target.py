from datetime import date, datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

class TargetCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    month: date
    target_value: int | None = Field(default=None, ge=0)

class TargetUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
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
    target_value: int | None
    current_value: int
    status: str
    created_at: datetime
    updated_at: datetime

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class UserProfileUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    college: str | None = Field(default=None, max_length=255)
    degree: str | None = Field(default=None, max_length=100)
    branch: str | None = Field(default=None, max_length=100)
    year: int | None = Field(default=None, ge=1, le=8)
    semester: int | None = Field(default=None, ge=1, le=16)
    timezone: str = Field(default="Asia/Kolkata", min_length=1, max_length=64)
    availability: dict | None = None
    preferences: dict | None = None
    onboarding_completed: bool = False


class UserProfileRead(UserProfileUpdate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    created_at: datetime
    updated_at: datetime

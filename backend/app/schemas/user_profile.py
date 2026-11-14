from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator


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

    @field_validator("timezone")
    @classmethod
    def valid_iana_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("timezone must be an IANA timezone name") from exc
        return value


class UserProfileRead(UserProfileUpdate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    created_at: datetime
    updated_at: datetime

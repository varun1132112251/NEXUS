from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ActivitySourceCreate(StrictSchema):
    name: str = Field(min_length=1, max_length=160)
    source_type: Literal["windows", "android"]

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value


class ActivitySourceRead(BaseModel):
    id: UUID
    name: str
    source_type: str
    created_at: datetime
    revoked_at: datetime | None


class ActivitySourceRegistered(ActivitySourceRead):
    credential: str


class ActivityDeviceEvent(StrictSchema):
    external_event_id: str = Field(min_length=1, max_length=255)
    event_type: Literal["app_focus", "idle", "active", "device_session"]
    occurred_at: datetime
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, allow_inf_nan=False)
    payload: dict[str, str | int | float | bool | None] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")

    @field_validator("external_event_id")
    @classmethod
    def event_id_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("external_event_id must not be blank")
        return value

    @field_validator("occurred_at")
    @classmethod
    def timestamp_must_have_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        return value

    @field_validator("payload")
    @classmethod
    def validate_payload(cls, value: dict[str, str | int | float | bool | None]):
        import json

        forbidden = {"user_id", "keystrokes", "password", "message", "screenshot", "document", "content", "text"}
        if len(value) > 32:
            raise ValueError("payload may contain at most 32 fields")
        if forbidden.intersection(key.lower() for key in value):
            raise ValueError("payload contains a prohibited field")
        if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > 4096:
            raise ValueError("payload must not exceed 4096 bytes")
        return value


class ActivityEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    source_id: UUID
    external_event_id: str
    event_type: str
    occurred_at: datetime
    received_at: datetime
    confidence: float
    payload: dict


class ActivityEventIngested(BaseModel):
    event: ActivityEventRead
    duplicate: bool = False

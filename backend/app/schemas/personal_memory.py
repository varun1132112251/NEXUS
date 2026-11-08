from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

MemoryCategory = Literal[
    "identity",
    "goal_context",
    "preference",
    "constraint",
    "commitment_context",
    "experience",
    "behavior_pattern",
]


class PersonalMemoryCreate(BaseModel):
    category: MemoryCategory
    title: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=1, max_length=10000)
    importance: int = Field(default=3, ge=1, le=5)
    details: dict = Field(default_factory=dict)
    source_reference: str | None = Field(default=None, max_length=255)
    supersedes_id: UUID | None = None
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def validate_expiry(self):
        if self.expires_at is not None and self.expires_at.tzinfo is None:
            raise ValueError("expires_at must include a timezone.")
        return self


class PersonalMemoryUpdate(BaseModel):
    category: MemoryCategory | None = None
    title: str | None = Field(default=None, min_length=1, max_length=160)
    content: str | None = Field(default=None, min_length=1, max_length=10000)
    importance: int | None = Field(default=None, ge=1, le=5)
    details: dict | None = None
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def validate_expiry(self):
        if self.expires_at is not None and self.expires_at.tzinfo is None:
            raise ValueError("expires_at must include a timezone.")
        return self


class PersonalMemoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    category: MemoryCategory
    title: str
    content: str
    source_kind: str
    confidence: float
    importance: int
    status: str
    source_reference: str | None
    details: dict
    supersedes_id: UUID | None
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ActivitySessionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    started_at: datetime
    ended_at: datetime
    duration_seconds: int = Field(ge=0)
    notes: str | None = None
    source_kind: Literal["observed", "manual"] = "manual"
    schedule_item_id: UUID | None = None
    task_id: UUID | None = None
    habit_id: UUID | None = None
    project_id: UUID | None = None
    target_id: UUID | None = None
    event_ids: list[UUID] = Field(default_factory=list, max_length=200)

    @field_validator("started_at", "ended_at")
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        return value

    @model_validator(mode="after")
    def source_rules(self):
        if self.ended_at <= self.started_at:
            raise ValueError("ended_at must be after started_at")
        if self.duration_seconds > (self.ended_at - self.started_at).total_seconds():
            raise ValueError("duration cannot exceed elapsed time")
        if self.source_kind == "observed" and not self.event_ids:
            raise ValueError("observed sessions require source events")
        if self.source_kind != "observed" and self.event_ids:
            raise ValueError("event_ids are only valid for observed sessions")
        if len(self.event_ids) != len(set(self.event_ids)):
            raise ValueError("event_ids must be unique")
        return self


class ActivitySessionCorrectionRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_seconds: int | None = Field(default=None, ge=0)
    notes: str | None = None
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("started_at", "ended_at")
    @classmethod
    def correction_timestamp_timezone(cls, value):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("timestamp must include a timezone")
        return value


class ContributionInput(BaseModel):
    target_id: UUID | None = None
    goal_id: UUID | None = None
    contribution_type: Literal["time", "metric", "milestone"]
    contribution_value: Decimal = Field(ge=0)
    unit: str | None = Field(default=None, max_length=32)
    details: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def one_destination(self):
        if (self.target_id is None) == (self.goal_id is None):
            raise ValueError("Provide exactly one target_id or goal_id")
        return self


class ContributionSet(BaseModel):
    contributions: list[ContributionInput] = Field(max_length=100)


class SplitRequest(BaseModel):
    split_at: datetime
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("split_at")
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("split_at must include a timezone")
        return value


class MergeRequest(BaseModel):
    other_session_id: UUID
    title: str | None = Field(default=None, min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=1000)


class ActivitySessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    user_id: UUID
    time_session_id: UUID | None
    schedule_item_id: UUID | None
    task_id: UUID | None
    habit_id: UUID | None
    project_id: UUID | None
    target_id: UUID | None
    title: str
    notes: str | None
    started_at: datetime
    ended_at: datetime | None
    duration_seconds: int | None
    confidence: float
    status: str
    source_kind: str
    created_at: datetime
    updated_at: datetime


class ActivityAssociationUpdate(BaseModel):
    schedule_item_id: UUID | None = None
    task_id: UUID | None = None
    habit_id: UUID | None = None
    project_id: UUID | None = None
    target_id: UUID | None = None


class ActivityEventWithSource(BaseModel):
    id: UUID
    source_id: UUID
    source_name: str
    source_type: str
    external_event_id: str
    event_type: str
    occurred_at: datetime
    received_at: datetime
    confidence: float
    payload: dict
    discarded_at: datetime | None
    session_ids: list[UUID]


class ActivityCorrectionRead(BaseModel):
    id: UUID
    field_name: str
    previous_value: object
    new_value: object
    reason: str | None
    created_at: datetime

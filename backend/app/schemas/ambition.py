from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

AmbitionStatus = Literal["active", "paused", "completed", "archived"]
GoalStatus = AmbitionStatus
MeasurementType = Literal["count", "duration", "distance", "weight", "currency", "percentage", "proficiency", "custom", "qualitative"]


class AmbitionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    category: str = Field(min_length=1, max_length=80)
    priority: int = Field(default=3, ge=1, le=5)
    start_date: date = Field(default_factory=date.today)
    target_date: date | None = None
    display_order: int = 0


class AmbitionUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    category: str | None = Field(default=None, min_length=1, max_length=80)
    priority: int | None = Field(default=None, ge=1, le=5)
    start_date: date | None = None
    target_date: date | None = None
    display_order: int | None = None


class AmbitionLifecycle(BaseModel):
    status: AmbitionStatus
    reason: str | None = Field(default=None, max_length=1000)


class AmbitionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    user_id: UUID
    title: str
    description: str | None
    category: str
    status: str
    priority: int
    start_date: date
    target_date: date | None
    completed_at: date | None
    display_order: int
    created_at: datetime
    updated_at: datetime


class AmbitionTemplate(BaseModel):
    title: str
    description: str
    category: str


class AmbitionLifecycleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    ambition_id: UUID
    previous_status: str
    new_status: str
    reason: str | None
    created_at: datetime


class GoalCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    supporting_project_id: UUID | None = None
    priority: int = Field(default=3, ge=1, le=5)
    start_date: date = Field(default_factory=date.today)
    target_date: date | None = None
    measurement_type: MeasurementType = "count"
    measurement_unit: str | None = Field(default=None, min_length=1, max_length=32)
    measurement_definition: str | None = None
    target_value: Decimal | None = Field(default=None, ge=0)


class GoalUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    supporting_project_id: UUID | None = None
    priority: int | None = Field(default=None, ge=1, le=5)
    start_date: date | None = None
    target_date: date | None = None
    status: GoalStatus | None = None
    measurement_type: MeasurementType | None = None
    measurement_unit: str | None = Field(default=None, min_length=1, max_length=32)
    measurement_definition: str | None = None
    target_value: Decimal | None = Field(default=None, ge=0)


class GoalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    user_id: UUID
    ambition_id: UUID
    supporting_project_id: UUID | None
    title: str
    description: str | None
    status: str
    priority: int
    start_date: date
    target_date: date | None
    completed_at: date | None
    measurement_type: str
    measurement_unit: str | None
    measurement_definition: str | None
    target_value: Decimal | None
    current_value: Decimal
    qualitative_value: str | None
    created_at: datetime
    updated_at: datetime


class MilestoneCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    due_date: date | None = None
    display_order: int = 0


class MilestoneUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    due_date: date | None = None
    status: Literal["open", "completed", "cancelled"] | None = None
    display_order: int | None = None


class MilestoneRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    user_id: UUID
    goal_id: UUID
    title: str
    description: str | None
    status: str
    due_date: date | None
    completed_at: date | None
    display_order: int
    created_at: datetime
    updated_at: datetime


class GoalProgressCreate(BaseModel):
    numeric_delta: Decimal | None = None
    qualitative_value: str | None = Field(default=None, min_length=1, max_length=4000)
    unit: str | None = Field(default=None, max_length=32)
    reason: str | None = Field(default=None, max_length=1000)
    details: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_one_value(self):
        if (self.numeric_delta is None) == (self.qualitative_value is None):
            raise ValueError("Provide exactly one numeric_delta or qualitative_value")
        return self


class GoalProgressCorrection(GoalProgressCreate):
    reason: str = Field(min_length=1, max_length=1000)


class GoalProgressRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    goal_id: UUID
    numeric_delta: Decimal | None
    resulting_value: Decimal | None
    qualitative_value: str | None
    unit: str | None
    source_kind: str
    source_contribution_id: UUID | None
    corrects_entry_id: UUID | None
    reason: str | None
    details: dict
    created_at: datetime


class TargetGoalLink(BaseModel):
    ambition_goal_id: UUID | None = None
    period_type: Literal["monthly", "weekly"] = "monthly"

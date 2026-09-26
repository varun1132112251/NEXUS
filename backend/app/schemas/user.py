from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    email: str
    created_at: datetime
    updated_at: datetime

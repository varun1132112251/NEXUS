from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LoginRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    username: str | None = Field(default=None, min_length=1, max_length=255)
    email: str | None = Field(default=None, min_length=1, max_length=255)
    password: Annotated[str, Field(min_length=1)]

    @field_validator("username", "email")
    @classmethod
    def strip_identifier(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return value.strip()

    @property
    def username_or_email(self) -> str:
        return self.username or self.email or ""

    @property
    def identifier(self) -> str:
        return self.username or self.email or ""


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

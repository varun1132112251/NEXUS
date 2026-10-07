from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LoginRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    username: str | None = Field(default=None, min_length=1, max_length=255)
    email: str | None = Field(default=None, min_length=1, max_length=255)
    password: Annotated[str, Field(min_length=8)]

    @field_validator("username", "email")
    @classmethod
    def strip_identifier(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else value

    @property
    def identifier(self) -> str:
        return self.username or self.email or ""


class EmailStartRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class EmailVerifyRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    code: str = Field(min_length=6, max_length=6)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class GoogleLoginRequest(BaseModel):
    credential: str = Field(min_length=1)


class AccountSetupRequest(BaseModel):
    setup_token: str = Field(min_length=1)
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=128)


class PasswordResetStartRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class PasswordResetCompleteRequest(BaseModel):
    reset_token: str = Field(min_length=1)
    password: str = Field(min_length=8, max_length=128)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class GoogleAuthResponse(BaseModel):
    requires_setup: bool
    access_token: str | None = None
    token_type: str = "bearer"
    setup_token: str | None = None
    email: str | None = None
    name: str | None = None

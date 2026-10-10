from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

Password = Annotated[str, Field(min_length=8, max_length=128)]
EmailAddress = Annotated[EmailStr, Field(max_length=255)]


class LoginRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    username: str | None = Field(default=None, min_length=1, max_length=255)
    email: EmailAddress | None = None
    password: Password

    @field_validator("username", "email")
    @classmethod
    def normalize_identifier(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = str(value).strip()
        if not value:
            raise ValueError("Identifier cannot be empty.")
        return value.lower() if "@" in value else value

    @property
    def identifier(self) -> str:
        return self.username or str(self.email or "")


class EmailStartRequest(BaseModel):
    email: EmailAddress

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()


class EmailVerifyRequest(BaseModel):
    email: EmailAddress
    code: str = Field(min_length=6, max_length=10)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip().upper()


class GoogleLoginRequest(BaseModel):
    credential: str = Field(min_length=1, max_length=16384)


class AccountSetupRequest(BaseModel):
    setup_token: str = Field(min_length=1, max_length=4096)
    username: str = Field(min_length=3, max_length=32)
    password: Password | None = None

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Username cannot be empty.")
        return value


class PasswordResetStartRequest(BaseModel):
    email: EmailAddress

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()


class PasswordResetVerifyRequest(BaseModel):
    email: EmailAddress
    reset_token: str = Field(min_length=6, max_length=10)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()

    @field_validator("reset_token")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip().upper()


class PasswordRecoverySessionRequest(BaseModel):
    email: EmailAddress
    recovery_session: str = Field(min_length=32, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()


class PasswordResetCompleteRequest(PasswordRecoverySessionRequest):
    password: Password


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

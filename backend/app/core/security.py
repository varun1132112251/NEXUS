from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import secrets
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError

from app.core.config import settings

_password_hasher = PasswordHasher()
_VERIFICATION_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, plain_password)
    except VerificationError:
        return False


def create_access_token(
    subject: str | UUID,
    expires_delta: timedelta | None = None,
    *,
    auth_version: int = 1,
) -> str:
    issued_at = datetime.now(UTC)
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.access_token_expire_minutes)
    payload = {
        "sub": str(subject),
        "iat": int(issued_at.timestamp()),
        "exp": int((issued_at + expires_delta).timestamp()),
        "ver": int(auth_version),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "exp", "iat"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise ValueError("Token has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise ValueError("Invalid token.") from exc


def create_auth_ticket(
    *,
    purpose: str,
    email: str,
    name: str | None = None,
    provider: str | None = None,
    provider_subject: str | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    issued_at = datetime.now(UTC)
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.auth_ticket_expire_minutes)
    payload = {
        "typ": "auth_ticket",
        "purpose": purpose,
        "email": email,
        "iat": int(issued_at.timestamp()),
        "exp": int((issued_at + expires_delta).timestamp()),
    }
    if name:
        payload["name"] = name
    if provider:
        payload["provider"] = provider
    if provider_subject:
        payload["provider_subject"] = provider_subject
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_auth_ticket(token: str, expected_purpose: str) -> dict:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["typ", "purpose", "email", "exp", "iat"]},
        )
    except jwt.InvalidTokenError as exc:
        raise ValueError("Invalid authentication ticket.") from exc
    if payload.get("typ") != "auth_ticket" or payload.get("purpose") != expected_purpose:
        raise ValueError("Invalid authentication ticket.")
    return payload


def create_one_time_token() -> str:
    return secrets.token_urlsafe(32)


def create_verification_code(length: int = 6) -> str:
    if length < 6 or length > 10:
        raise ValueError("Verification code length must be between 6 and 10.")
    return "".join(secrets.choice(_VERIFICATION_ALPHABET) for _ in range(length))


def hash_one_time_token(token: str, *, context: str = "") -> str:
    # Keyed HMAC prevents a database-only leak from enabling offline guessing
    # of short verification codes. The context isolates accounts and purposes.
    message = (context + "\0" + token).encode("utf-8")
    return hmac.new(
        settings.jwt_secret_key.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()

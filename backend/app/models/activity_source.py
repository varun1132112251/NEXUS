from datetime import UTC, datetime
import hashlib
import hmac
import secrets
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy import select
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class ActivitySource(Base):
    """A user-owned source of raw activity signals."""

    __tablename__ = "activity_sources"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_activity_sources_id_user_id"),
        UniqueConstraint("user_id", "name", name="uq_activity_sources_user_name"),
        Index("ix_activity_sources_user_revoked", "user_id", "revoked_at"),
    )

    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    credential_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    @classmethod
    def active_for_credential(cls, db, credential: str):
        """Resolve an active source by raw credential without storing the credential."""
        try:
            digest = credential_digest(credential)
        except RuntimeError:
            return None
        source = db.execute(
            select(cls).where(cls.credential_hash == digest, cls.revoked_at.is_(None))
        ).scalar_one_or_none()
        return source if source is not None and verify_credential(credential, source.credential_hash) else None


def _credential_key() -> bytes:
    from app.core.config import settings

    if not settings.activity_source_hmac_key:
        raise RuntimeError("ACTIVITY_SOURCE_HMAC_KEY must be configured")
    key = settings.activity_source_hmac_key.encode("utf-8")
    if len(key) < 32:
        raise RuntimeError("ACTIVITY_SOURCE_HMAC_KEY must contain at least 32 bytes")
    return key


def credential_digest(credential: str) -> str:
    return hmac.new(_credential_key(), credential.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_credential(credential: str, stored_digest: str) -> bool:
    """Constant-time verification of a high-entropy device bearer secret."""
    try:
        candidate = credential_digest(credential)
    except RuntimeError:
        return False
    return hmac.compare_digest(candidate, stored_digest)


def issue_credential(db, *, user_id: UUID, name: str, source_type: str) -> tuple[ActivitySource, str]:
    """Persist only the keyed digest and return the raw credential once."""
    credential = secrets.token_urlsafe(32)
    source = ActivitySource(
        user_id=user_id, name=name, source_type=source_type,
        credential_hash=credential_digest(credential),
    )
    db.add(source)
    db.flush()
    return source, credential

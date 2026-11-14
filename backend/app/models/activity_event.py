from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class ActivityEvent(Base):
    """A source-provided signal, retained as data rather than verified productivity."""

    __tablename__ = "activity_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["source_id", "user_id"],
            ["activity_sources.id", "activity_sources.user_id"],
            ondelete="CASCADE",
            name="fk_activity_events_source_user",
        ),
        UniqueConstraint(
            "source_id",
            "external_event_id",
            name="uq_activity_events_source_external_event",
        ),
        UniqueConstraint("id", "user_id", name="uq_activity_events_id_user_id"),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_activity_events_confidence",
        ),
        Index("ix_activity_events_user_occurred_at", "user_id", "occurred_at"),
        Index("ix_activity_events_source_occurred_at", "source_id", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    external_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=text("CURRENT_TIMESTAMP")
    )
    confidence: Mapped[float] = mapped_column(nullable=False, default=0.0, server_default="0.0")
    payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    discarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=text("CURRENT_TIMESTAMP")
    )

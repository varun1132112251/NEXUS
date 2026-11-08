from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class PersonalMemory(Base):
    """A durable, user-scoped piece of personal context with explicit provenance."""

    __tablename__ = "personal_memories"
    __table_args__ = (
        CheckConstraint(
            "category IN ('identity', 'goal_context', 'preference', 'constraint', "
            "'commitment_context', 'experience', 'behavior_pattern')",
            name="ck_personal_memories_category",
        ),
        CheckConstraint(
            "source_kind IN ('user_stated', 'system_observed', 'agent_inferred', 'imported')",
            name="ck_personal_memories_source_kind",
        ),
        CheckConstraint(
            "status IN ('active', 'superseded', 'archived')",
            name="ck_personal_memories_status",
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_personal_memories_confidence"),
        CheckConstraint("importance >= 1 AND importance <= 5", name="ck_personal_memories_importance"),
        Index("ix_personal_memories_user_status_category", "user_id", "status", "category"),
        Index("ix_personal_memories_user_updated", "user_id", "updated_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_kind: Mapped[str] = mapped_column(
        String(24), nullable=False, default="user_stated", server_default="user_stated"
    )
    confidence: Mapped[float] = mapped_column(nullable=False, default=1.0, server_default="1.0")
    importance: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default="3")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", server_default="active")
    source_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    supersedes_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("personal_memories.id", ondelete="SET NULL"), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )

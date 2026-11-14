from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class ActivitySession(Base):
    """A reviewable interpretation of activity, not a replacement for TimeSession."""

    __tablename__ = "activity_sessions"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_activity_sessions_id_user_id"),
        ForeignKeyConstraint(["time_session_id", "user_id"], ["time_sessions.id", "time_sessions.user_id"], name="fk_activity_sessions_time_session_user"),
        ForeignKeyConstraint(["schedule_item_id", "user_id"], ["schedule_items.id", "schedule_items.user_id"], name="fk_activity_sessions_schedule_user"),
        ForeignKeyConstraint(["task_id", "user_id"], ["tasks.id", "tasks.user_id"], name="fk_activity_sessions_task_user"),
        ForeignKeyConstraint(["habit_id", "user_id"], ["habits.id", "habits.user_id"], name="fk_activity_sessions_habit_user"),
        ForeignKeyConstraint(["project_id", "user_id"], ["projects.id", "projects.user_id"], name="fk_activity_sessions_project_user"),
        ForeignKeyConstraint(["target_id", "user_id"], ["targets.id", "targets.user_id"], name="fk_activity_sessions_target_user"),
        CheckConstraint(
            "status IN ('draft', 'confirmed', 'corrected', 'discarded', 'superseded')",
            name="ck_activity_sessions_status",
        ),
        CheckConstraint(
            "source_kind IN ('observed', 'manual', 'stopwatch', 'merged', 'legacy')",
            name="ck_activity_sessions_source_kind",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_activity_sessions_confidence",
        ),
        CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds >= 0",
            name="ck_activity_sessions_duration",
        ),
        CheckConstraint(
            "ended_at IS NULL OR ended_at > started_at",
            name="ck_activity_sessions_time_range",
        ),
        CheckConstraint(
            "(status = 'draft' AND ((ended_at IS NULL AND duration_seconds IS NULL) OR "
            "(ended_at IS NOT NULL AND ended_at > started_at AND duration_seconds IS NOT NULL "
            "AND duration_seconds >= 0 AND duration_seconds <= floor(extract(epoch FROM (ended_at - started_at)))))) OR "
            "(status IN ('confirmed', 'corrected') AND ended_at IS NOT NULL AND ended_at > started_at "
            "AND duration_seconds IS NOT NULL AND duration_seconds >= 0 "
            "AND duration_seconds <= floor(extract(epoch FROM (ended_at - started_at)))) OR "
            "(status IN ('discarded', 'superseded') AND (duration_seconds IS NULL OR "
            "(ended_at IS NOT NULL AND ended_at > started_at AND duration_seconds >= 0 "
            "AND duration_seconds <= floor(extract(epoch FROM (ended_at - started_at))))))",
            name="ck_activity_sessions_status_timing",
        ),
        Index(
            "uq_activity_sessions_time_session",
            "time_session_id",
            unique=True,
            postgresql_where=text("time_session_id IS NOT NULL"),
        ),
        Index("ix_activity_sessions_user_status_started", "user_id", "status", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    time_session_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True, index=True
    )
    schedule_item_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True, index=True
    )
    task_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True, index=True
    )
    habit_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True, index=True
    )
    project_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True, index=True
    )
    target_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[float] = mapped_column(nullable=False, default=0.0, server_default="0.0")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="draft", server_default="draft"
    )
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="legacy", server_default="legacy")
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

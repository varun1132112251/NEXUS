from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class TimeSession(Base):
    __tablename__ = "time_sessions"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_time_sessions_id_user_id"),
        # Composite ownership FKs are restrictive. Callers must explicitly clear
        # the nullable link before deleting its parent; user_id is never nulled.
        ForeignKeyConstraint(["schedule_item_id", "user_id"], ["schedule_items.id", "schedule_items.user_id"], name="fk_time_sessions_schedule_user"),
        ForeignKeyConstraint(["task_id", "user_id"], ["tasks.id", "tasks.user_id"], name="fk_time_sessions_task_user"),
        ForeignKeyConstraint(["habit_id", "user_id"], ["habits.id", "habits.user_id"], name="fk_time_sessions_habit_user"),
        ForeignKeyConstraint(["project_id", "user_id"], ["projects.id", "projects.user_id"], name="fk_time_sessions_project_user"),
        ForeignKeyConstraint(["target_id", "user_id"], ["targets.id", "targets.user_id"], name="fk_time_sessions_target_user"),
        CheckConstraint("status IN ('running', 'completed', 'cancelled')", name="ck_time_sessions_status"),
        CheckConstraint("duration_seconds IS NULL OR duration_seconds >= 0", name="ck_time_sessions_duration"),
        CheckConstraint("(status = 'running' AND ended_at IS NULL AND duration_seconds IS NULL) OR (status = 'completed' AND ended_at IS NOT NULL AND ended_at > started_at AND duration_seconds IS NOT NULL AND duration_seconds >= 0 AND duration_seconds <= floor(extract(epoch FROM (ended_at - started_at)))) OR (status = 'cancelled' AND duration_seconds IS NULL AND (ended_at IS NULL OR ended_at > started_at))", name="ck_time_sessions_status_timing"),
        Index(
            "uq_time_sessions_one_running_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'running'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    schedule_item_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)
    task_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)
    habit_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)
    project_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)
    target_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running", server_default="running")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now, server_default=text("CURRENT_TIMESTAMP"))

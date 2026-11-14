from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_tasks_id_user_id"),
        ForeignKeyConstraint(["project_id", "user_id"], ["projects.id", "projects.user_id"], name="fk_tasks_project_user"),
        ForeignKeyConstraint(["target_id", "user_id"], ["targets.id", "targets.user_id"], name="fk_tasks_target_user"),
        ForeignKeyConstraint(["ambition_goal_id", "user_id"], ["ambition_goals.id", "ambition_goals.user_id"], name="fk_tasks_ambition_goal_user"),
        CheckConstraint("status IN ('planned', 'in_progress', 'completed', 'blocked', 'cancelled')", name="ck_tasks_status"),
        CheckConstraint("priority BETWEEN 1 AND 5", name="ck_tasks_priority"),
        Index("ix_tasks_user_live_due_priority", "user_id", "due_at", "priority", postgresql_where=text("deleted_at IS NULL")),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)
    target_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)
    ambition_goal_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="planned", server_default="planned")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default="3")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now, server_default=text("CURRENT_TIMESTAMP"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

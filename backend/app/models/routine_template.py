from datetime import UTC, datetime, time
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, ForeignKeyConstraint, Integer, JSON, String, Text, Time, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class RoutineTemplate(Base):
    __tablename__ = "routine_templates"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_routine_templates_id_user_id"),
        ForeignKeyConstraint(["habit_id", "user_id"], ["habits.id", "habits.user_id"], name="fk_routine_templates_habit_user"),
        ForeignKeyConstraint(["task_id", "user_id"], ["tasks.id", "tasks.user_id"], name="fk_routine_templates_task_user"),
        ForeignKeyConstraint(["project_id", "user_id"], ["projects.id", "projects.user_id"], name="fk_routine_templates_project_user"),
        ForeignKeyConstraint(["target_id", "user_id"], ["targets.id", "targets.user_id"], name="fk_routine_templates_target_user"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    habit_id: Mapped[UUID | None] = mapped_column(ForeignKey("habits.id", ondelete="SET NULL"), nullable=True, index=True)
    task_id: Mapped[UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True)
    project_id: Mapped[UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True)
    target_id: Mapped[UUID | None] = mapped_column(ForeignKey("targets.id", ondelete="SET NULL"), nullable=True, index=True)

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    weekdays: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default=text("'[]'::json"))
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default="3")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now, server_default=text("CURRENT_TIMESTAMP"))

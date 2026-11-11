from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, ForeignKeyConstraint, Integer, String, Text, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class ScheduleItem(Base):
    __tablename__ = "schedule_items"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_schedule_items_id_user_id"),
        # Clear optional references before deleting a parent; composite SET NULL
        # would also attempt to null the required user_id.
        ForeignKeyConstraint(["task_id", "user_id"], ["tasks.id", "tasks.user_id"], name="fk_schedule_items_task_user"),
        ForeignKeyConstraint(["habit_id", "user_id"], ["habits.id", "habits.user_id"], name="fk_schedule_items_habit_user"),
        ForeignKeyConstraint(["project_id", "user_id"], ["projects.id", "projects.user_id"], name="fk_schedule_items_project_user"),
        ForeignKeyConstraint(["target_id", "user_id"], ["targets.id", "targets.user_id"], name="fk_schedule_items_target_user"),
        CheckConstraint("end_at > start_at", name="ck_schedule_items_time_range"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)
    habit_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)
    project_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)
    target_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    scheduled_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default="3")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="planned", server_default="planned")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now, server_default=text("CURRENT_TIMESTAMP"))

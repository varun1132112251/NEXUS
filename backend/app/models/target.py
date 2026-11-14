from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, ForeignKeyConstraint, Integer, String, Text, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class Target(Base):
    __tablename__ = "targets"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_targets_id_user_id"),
        ForeignKeyConstraint(["ambition_goal_id", "user_id"], ["ambition_goals.id", "ambition_goals.user_id"], name="fk_targets_ambition_goal_user"),
        CheckConstraint("period_type IN ('monthly', 'weekly')", name="ck_targets_period_type"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    month: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    period_type: Mapped[str] = mapped_column(String(12), nullable=False, default="monthly", server_default="monthly")
    ambition_goal_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)
    metric_type: Mapped[str] = mapped_column(String(64), nullable=False, default="count", server_default="count")
    target_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_value: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", server_default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now, server_default=text("CURRENT_TIMESTAMP"))

    @property
    def period_start(self) -> date:
        return self.month

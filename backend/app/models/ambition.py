from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class Ambition(Base):
    __tablename__ = "ambitions"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_ambitions_id_user_id"),
        CheckConstraint("status IN ('active', 'paused', 'completed', 'archived')", name="ck_ambitions_status"),
        CheckConstraint("priority BETWEEN 1 AND 5", name="ck_ambitions_priority"),
        CheckConstraint("target_date IS NULL OR target_date >= start_date", name="ck_ambitions_dates"),
        Index("ix_ambitions_user_status_order", "user_id", "status", "display_order"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", server_default="active")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default="3")
    start_date: Mapped[date] = mapped_column(Date, nullable=False, default=date.today, server_default=text("CURRENT_DATE"))
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    completed_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now, server_default=text("CURRENT_TIMESTAMP"))

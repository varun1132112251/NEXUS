from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, Numeric, String, Text, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class AmbitionGoal(Base):
    __tablename__ = "ambition_goals"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_ambition_goals_id_user_id"),
        ForeignKeyConstraint(["ambition_id", "user_id"], ["ambitions.id", "ambitions.user_id"], ondelete="RESTRICT", name="fk_ambition_goals_ambition_user"),
        ForeignKeyConstraint(["supporting_project_id", "user_id"], ["projects.id", "projects.user_id"], ondelete="RESTRICT", name="fk_ambition_goals_project_user"),
        CheckConstraint("status IN ('active', 'paused', 'completed', 'archived')", name="ck_ambition_goals_status"),
        CheckConstraint("priority BETWEEN 1 AND 5", name="ck_ambition_goals_priority"),
        CheckConstraint("target_date IS NULL OR target_date >= start_date", name="ck_ambition_goals_dates"),
        CheckConstraint("measurement_type IN ('count', 'duration', 'distance', 'weight', 'currency', 'percentage', 'proficiency', 'custom', 'qualitative')", name="ck_ambition_goals_measurement_type"),
        Index("ix_ambition_goals_user_ambition_status", "user_id", "ambition_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    ambition_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    supporting_project_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", server_default="active")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default="3")
    start_date: Mapped[date] = mapped_column(Date, nullable=False, default=date.today, server_default=text("CURRENT_DATE"))
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    completed_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    measurement_type: Mapped[str] = mapped_column(String(24), nullable=False, default="count", server_default="count")
    measurement_unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    measurement_definition: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_value: Mapped[Decimal | None] = mapped_column(Numeric(16, 4), nullable=True)
    current_value: Mapped[Decimal] = mapped_column(Numeric(16, 4), nullable=False, default=Decimal("0"), server_default="0")
    qualitative_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now, server_default=text("CURRENT_TIMESTAMP"))

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, Numeric, String, Text, UniqueConstraint, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import DDL, event

from app.db.base import Base


class GoalProgressEntry(Base):
    """Append-only measurement history; corrections are new signed entries."""

    __tablename__ = "goal_progress_entries"
    __table_args__ = (
        ForeignKeyConstraint(["goal_id", "user_id"], ["ambition_goals.id", "ambition_goals.user_id"], ondelete="RESTRICT", name="fk_goal_progress_entries_goal_user"),
        ForeignKeyConstraint(["corrects_entry_id", "user_id"], ["goal_progress_entries.id", "goal_progress_entries.user_id"], ondelete="RESTRICT", name="fk_goal_progress_entries_correction_user"),
        UniqueConstraint("id", "user_id", name="uq_goal_progress_entries_id_user_id"),
        CheckConstraint("source_kind IN ('manual', 'activity', 'correction', 'milestone')", name="ck_goal_progress_entries_source"),
        CheckConstraint("(numeric_delta IS NOT NULL) OR (qualitative_value IS NOT NULL)", name="ck_goal_progress_entries_value"),
        Index("ix_goal_progress_entries_goal_created", "goal_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    goal_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    numeric_delta: Mapped[Decimal | None] = mapped_column(Numeric(16, 4), nullable=True)
    resulting_value: Mapped[Decimal | None] = mapped_column(Numeric(16, 4), nullable=True)
    qualitative_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="manual", server_default="manual")
    source_contribution_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    corrects_entry_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), server_default=text("CURRENT_TIMESTAMP"))


event.listen(
    GoalProgressEntry.__table__,
    "after_create",
    DDL("""
    CREATE FUNCTION nexus_reject_goal_progress_mutation() RETURNS trigger AS $$
    BEGIN
      RAISE EXCEPTION 'goal progress history is append-only';
    END; $$ LANGUAGE plpgsql;
    CREATE TRIGGER trg_goal_progress_immutable
      BEFORE UPDATE OR DELETE ON goal_progress_entries
      FOR EACH ROW EXECUTE FUNCTION nexus_reject_goal_progress_mutation();
    """),
)
event.listen(GoalProgressEntry.__table__, "before_drop", DDL("DROP FUNCTION IF EXISTS nexus_reject_goal_progress_mutation();"))

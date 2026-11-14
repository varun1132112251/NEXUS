from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, String, Text, Uuid, text
from sqlalchemy import DDL, event
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AmbitionLifecycleEvent(Base):
    """Append-only lifecycle audit, including completion and later resumption."""

    __tablename__ = "ambition_lifecycle_events"
    __table_args__ = (
        ForeignKeyConstraint(["ambition_id", "user_id"], ["ambitions.id", "ambitions.user_id"], ondelete="RESTRICT", name="fk_ambition_lifecycle_events_ambition_user"),
        CheckConstraint("previous_status IN ('active', 'paused', 'completed', 'archived')", name="ck_ambition_lifecycle_events_previous"),
        CheckConstraint("new_status IN ('active', 'paused', 'completed', 'archived')", name="ck_ambition_lifecycle_events_new"),
        Index("ix_ambition_lifecycle_events_user_ambition_created", "user_id", "ambition_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    ambition_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    previous_status: Mapped[str] = mapped_column(String(16), nullable=False)
    new_status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), server_default=text("CURRENT_TIMESTAMP"))


event.listen(
    AmbitionLifecycleEvent.__table__, "after_create",
    DDL("""
    CREATE FUNCTION nexus_reject_ambition_lifecycle_mutation() RETURNS trigger AS $$
    BEGIN RAISE EXCEPTION 'ambition lifecycle history is append-only'; END; $$ LANGUAGE plpgsql;
    CREATE TRIGGER trg_ambition_lifecycle_immutable BEFORE UPDATE OR DELETE ON ambition_lifecycle_events
      FOR EACH ROW EXECUTE FUNCTION nexus_reject_ambition_lifecycle_mutation();
    """),
)
event.listen(AmbitionLifecycleEvent.__table__, "before_drop", DDL("DROP FUNCTION IF EXISTS nexus_reject_ambition_lifecycle_mutation();"))

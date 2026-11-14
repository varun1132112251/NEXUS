from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, String, Uuid, text
from sqlalchemy import DDL, event
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ScheduleStatusEvent(Base):
    """Append-only audit of schedule block lifecycle changes."""

    __tablename__ = "schedule_status_events"
    __table_args__ = (
        ForeignKeyConstraint(["schedule_item_id", "user_id"], ["schedule_items.id", "schedule_items.user_id"], ondelete="RESTRICT", name="fk_schedule_status_events_item_user"),
        CheckConstraint("previous_status IS NULL OR previous_status IN ('planned', 'partial', 'completed', 'skipped', 'missed', 'cancelled')", name="ck_schedule_status_events_previous"),
        CheckConstraint("new_status IN ('planned', 'partial', 'completed', 'skipped', 'missed', 'cancelled')", name="ck_schedule_status_events_new"),
        CheckConstraint("event_kind IN ('baseline', 'created', 'changed')", name="ck_schedule_status_events_kind"),
        Index("ix_schedule_status_events_user_item_created", "user_id", "schedule_item_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4, server_default=text("gen_random_uuid()"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    schedule_item_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    previous_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    new_status: Mapped[str] = mapped_column(String(16), nullable=False)
    event_kind: Mapped[str] = mapped_column(String(12), nullable=False, default="changed", server_default="changed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), server_default=text("CURRENT_TIMESTAMP"))


event.listen(ScheduleStatusEvent.__table__, "after_create", DDL("""
CREATE FUNCTION nexus_record_schedule_status() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    INSERT INTO schedule_status_events(user_id, schedule_item_id, previous_status, new_status, event_kind)
      VALUES (NEW.user_id, NEW.id, NULL, NEW.status, 'created');
  ELSIF NEW.status IS DISTINCT FROM OLD.status THEN
    INSERT INTO schedule_status_events(user_id, schedule_item_id, previous_status, new_status, event_kind)
      VALUES (NEW.user_id, NEW.id, OLD.status, NEW.status, 'changed');
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER trg_schedule_items_status_insert AFTER INSERT ON schedule_items
  FOR EACH ROW EXECUTE FUNCTION nexus_record_schedule_status();
CREATE TRIGGER trg_schedule_items_status_update AFTER UPDATE OF status ON schedule_items
  FOR EACH ROW EXECUTE FUNCTION nexus_record_schedule_status();
CREATE FUNCTION nexus_reject_schedule_status_event_mutation() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION 'schedule status history is append-only'; END; $$ LANGUAGE plpgsql;
CREATE TRIGGER trg_schedule_status_events_immutable BEFORE UPDATE OR DELETE ON schedule_status_events
  FOR EACH ROW EXECUTE FUNCTION nexus_reject_schedule_status_event_mutation();
"""))
event.listen(ScheduleStatusEvent.__table__, "before_drop", DDL("""
DROP TRIGGER IF EXISTS trg_schedule_items_status_insert ON schedule_items;
DROP TRIGGER IF EXISTS trg_schedule_items_status_update ON schedule_items;
DROP TRIGGER IF EXISTS trg_schedule_status_events_immutable ON schedule_status_events;
DROP FUNCTION IF EXISTS nexus_record_schedule_status();
DROP FUNCTION IF EXISTS nexus_reject_schedule_status_event_mutation();
"""))

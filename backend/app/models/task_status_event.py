from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, String, Uuid, text
from sqlalchemy import DDL, event
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TaskStatusEvent(Base):
    """Append-only audit of task lifecycle changes."""

    __tablename__ = "task_status_events"
    __table_args__ = (
        ForeignKeyConstraint(["task_id", "user_id"], ["tasks.id", "tasks.user_id"], ondelete="RESTRICT", name="fk_task_status_events_task_user"),
        CheckConstraint("previous_status IS NULL OR previous_status IN ('planned', 'in_progress', 'completed', 'blocked', 'cancelled')", name="ck_task_status_events_previous"),
        CheckConstraint("new_status IN ('planned', 'in_progress', 'completed', 'blocked', 'cancelled')", name="ck_task_status_events_new"),
        CheckConstraint("event_kind IN ('baseline', 'created', 'changed')", name="ck_task_status_events_kind"),
        Index("ix_task_status_events_user_task_created", "user_id", "task_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4, server_default=text("gen_random_uuid()"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    task_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    previous_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    new_status: Mapped[str] = mapped_column(String(16), nullable=False)
    event_kind: Mapped[str] = mapped_column(String(12), nullable=False, default="changed", server_default="changed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), server_default=text("CURRENT_TIMESTAMP"))


event.listen(TaskStatusEvent.__table__, "after_create", DDL("""
CREATE FUNCTION nexus_record_task_status() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    INSERT INTO task_status_events(user_id, task_id, previous_status, new_status, event_kind)
      VALUES (NEW.user_id, NEW.id, NULL, NEW.status, 'created');
  ELSIF NEW.status IS DISTINCT FROM OLD.status THEN
    INSERT INTO task_status_events(user_id, task_id, previous_status, new_status, event_kind)
      VALUES (NEW.user_id, NEW.id, OLD.status, NEW.status, 'changed');
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER trg_tasks_status_insert AFTER INSERT ON tasks
  FOR EACH ROW EXECUTE FUNCTION nexus_record_task_status();
CREATE TRIGGER trg_tasks_status_update AFTER UPDATE OF status ON tasks
  FOR EACH ROW EXECUTE FUNCTION nexus_record_task_status();
CREATE FUNCTION nexus_reject_task_status_event_mutation() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION 'task status history is append-only'; END; $$ LANGUAGE plpgsql;
CREATE TRIGGER trg_task_status_events_immutable BEFORE UPDATE OR DELETE ON task_status_events
  FOR EACH ROW EXECUTE FUNCTION nexus_reject_task_status_event_mutation();
"""))
event.listen(TaskStatusEvent.__table__, "before_drop", DDL("""
DROP TRIGGER IF EXISTS trg_tasks_status_insert ON tasks;
DROP TRIGGER IF EXISTS trg_tasks_status_update ON tasks;
DROP TRIGGER IF EXISTS trg_task_status_events_immutable ON task_status_events;
DROP FUNCTION IF EXISTS nexus_record_task_status();
DROP FUNCTION IF EXISTS nexus_reject_task_status_event_mutation();
"""))

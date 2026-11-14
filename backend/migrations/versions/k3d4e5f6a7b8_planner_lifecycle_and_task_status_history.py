"""constrain planner lifecycle and preserve status history

Revision ID: k3d4e5f6a7b8
Revises: j2c3d4e5f6a1
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "k3d4e5f6a7b8"
down_revision: str | Sequence[str] | None = "j2c3d4e5f6a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TASK_STATUSES = "'planned', 'in_progress', 'completed', 'blocked', 'cancelled'"
SCHEDULE_STATUSES = "'planned', 'partial', 'completed', 'skipped', 'missed', 'cancelled'"


def upgrade() -> None:
    bind = op.get_bind()
    invalid_tasks = bind.execute(sa.text(f"SELECT count(*) FROM tasks WHERE status NOT IN ({TASK_STATUSES}) OR priority NOT BETWEEN 1 AND 5")).scalar_one()
    invalid_schedules = bind.execute(sa.text(f"SELECT count(*) FROM schedule_items WHERE status NOT IN ({SCHEDULE_STATUSES}) OR priority NOT BETWEEN 1 AND 5")).scalar_one()
    if invalid_tasks or invalid_schedules:
        raise RuntimeError(
            "Cannot upgrade planner lifecycle: existing task/schedule status or priority values are outside the new contract. "
            "Review and correct those rows explicitly before retrying; this migration does not rewrite user data."
        )

    op.add_column("tasks", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("schedule_items", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_tasks_user_live_due_priority", "tasks", ["user_id", "due_at", "priority"], postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("ix_schedule_items_user_live_date", "schedule_items", ["user_id", "scheduled_date"], postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("ix_schedule_items_user_live_start", "schedule_items", ["user_id", "start_at", "end_at"], postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_check_constraint("ck_tasks_status", "tasks", f"status IN ({TASK_STATUSES})")
    op.create_check_constraint("ck_tasks_priority", "tasks", "priority BETWEEN 1 AND 5")
    op.create_check_constraint("ck_schedule_items_status", "schedule_items", f"status IN ({SCHEDULE_STATUSES})")
    op.create_check_constraint("ck_schedule_items_priority", "schedule_items", "priority BETWEEN 1 AND 5")

    op.create_table(
        "task_status_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("previous_status", sa.String(length=16), nullable=True),
        sa.Column("new_status", sa.String(length=16), nullable=False),
        sa.Column("event_kind", sa.String(length=12), server_default="changed", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint(f"previous_status IS NULL OR previous_status IN ({TASK_STATUSES})", name="ck_task_status_events_previous"),
        sa.CheckConstraint(f"new_status IN ({TASK_STATUSES})", name="ck_task_status_events_new"),
        sa.CheckConstraint("event_kind IN ('baseline', 'created', 'changed')", name="ck_task_status_events_kind"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["task_id", "user_id"], ["tasks.id", "tasks.user_id"], name="fk_task_status_events_task_user", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_task_status_events_user_id", "task_status_events", ["user_id"])
    op.create_index("ix_task_status_events_task_id", "task_status_events", ["task_id"])
    op.create_index("ix_task_status_events_user_task_created", "task_status_events", ["user_id", "task_id", "created_at"])
    op.execute(sa.text(f"""
        INSERT INTO task_status_events(user_id, task_id, previous_status, new_status, event_kind, created_at)
        SELECT user_id, id, NULL, status, 'baseline', created_at FROM tasks
    """))

    op.create_table(
        "schedule_status_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("schedule_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("previous_status", sa.String(length=16), nullable=True),
        sa.Column("new_status", sa.String(length=16), nullable=False),
        sa.Column("event_kind", sa.String(length=12), server_default="changed", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint(f"previous_status IS NULL OR previous_status IN ({SCHEDULE_STATUSES})", name="ck_schedule_status_events_previous"),
        sa.CheckConstraint(f"new_status IN ({SCHEDULE_STATUSES})", name="ck_schedule_status_events_new"),
        sa.CheckConstraint("event_kind IN ('baseline', 'created', 'changed')", name="ck_schedule_status_events_kind"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["schedule_item_id", "user_id"], ["schedule_items.id", "schedule_items.user_id"], name="fk_schedule_status_events_item_user", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_schedule_status_events_user_id", "schedule_status_events", ["user_id"])
    op.create_index("ix_schedule_status_events_schedule_item_id", "schedule_status_events", ["schedule_item_id"])
    op.create_index("ix_schedule_status_events_user_item_created", "schedule_status_events", ["user_id", "schedule_item_id", "created_at"])
    op.execute(sa.text("""
        INSERT INTO schedule_status_events(user_id, schedule_item_id, previous_status, new_status, event_kind, created_at)
        SELECT user_id, id, NULL, status, 'baseline', created_at FROM schedule_items
    """))

    op.execute(sa.text("""
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

        CREATE FUNCTION nexus_reject_planner_status_event_mutation() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'planner status history is append-only'; END; $$ LANGUAGE plpgsql;
        CREATE TRIGGER trg_task_status_events_immutable BEFORE UPDATE OR DELETE ON task_status_events
          FOR EACH ROW EXECUTE FUNCTION nexus_reject_planner_status_event_mutation();
        CREATE TRIGGER trg_schedule_status_events_immutable BEFORE UPDATE OR DELETE ON schedule_status_events
          FOR EACH ROW EXECUTE FUNCTION nexus_reject_planner_status_event_mutation();
    """))


def downgrade() -> None:
    bind = op.get_bind()
    unsafe = bind.execute(sa.text("""
        SELECT
          EXISTS (SELECT 1 FROM tasks WHERE deleted_at IS NOT NULL) AS deleted_tasks,
          EXISTS (SELECT 1 FROM schedule_items WHERE deleted_at IS NOT NULL) AS deleted_schedule_items,
          EXISTS (SELECT 1 FROM task_status_events WHERE event_kind <> 'baseline') AS task_history,
          EXISTS (SELECT 1 FROM schedule_status_events WHERE event_kind <> 'baseline') AS schedule_history,
          EXISTS (SELECT 1 FROM schedule_items WHERE status IN ('missed', 'cancelled')) AS schedule_states
    """)).mappings().one()
    if any(unsafe.values()):
        raise RuntimeError("Cannot downgrade planner lifecycle: user-created status history, soft-deleted items, or new lifecycle states would be lost.")

    op.execute(sa.text("""
        DROP TRIGGER IF EXISTS trg_tasks_status_insert ON tasks;
        DROP TRIGGER IF EXISTS trg_tasks_status_update ON tasks;
        DROP TRIGGER IF EXISTS trg_schedule_items_status_insert ON schedule_items;
        DROP TRIGGER IF EXISTS trg_schedule_items_status_update ON schedule_items;
        DROP TRIGGER IF EXISTS trg_task_status_events_immutable ON task_status_events;
        DROP TRIGGER IF EXISTS trg_schedule_status_events_immutable ON schedule_status_events;
        DROP FUNCTION IF EXISTS nexus_record_task_status();
        DROP FUNCTION IF EXISTS nexus_record_schedule_status();
        DROP FUNCTION IF EXISTS nexus_reject_planner_status_event_mutation();
    """))
    op.drop_index("ix_schedule_status_events_user_item_created", table_name="schedule_status_events")
    op.drop_index("ix_schedule_status_events_schedule_item_id", table_name="schedule_status_events")
    op.drop_index("ix_schedule_status_events_user_id", table_name="schedule_status_events")
    op.drop_table("schedule_status_events")
    op.drop_index("ix_task_status_events_user_task_created", table_name="task_status_events")
    op.drop_index("ix_task_status_events_task_id", table_name="task_status_events")
    op.drop_index("ix_task_status_events_user_id", table_name="task_status_events")
    op.drop_table("task_status_events")
    op.drop_constraint("ck_schedule_items_priority", "schedule_items", type_="check")
    op.drop_constraint("ck_schedule_items_status", "schedule_items", type_="check")
    op.drop_constraint("ck_tasks_priority", "tasks", type_="check")
    op.drop_constraint("ck_tasks_status", "tasks", type_="check")
    op.drop_index("ix_schedule_items_user_live_start", table_name="schedule_items")
    op.drop_index("ix_schedule_items_user_live_date", table_name="schedule_items")
    op.drop_index("ix_tasks_user_live_due_priority", table_name="tasks")
    op.drop_column("schedule_items", "deleted_at")
    op.drop_column("tasks", "deleted_at")

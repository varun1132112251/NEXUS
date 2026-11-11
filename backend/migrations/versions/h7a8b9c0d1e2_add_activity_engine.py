"""add Activity Engine schema and database enforcement

Revision ID: h7a8b9c0d1e2
Revises: g1a2b3c4d5e6

The downgrade drops all Activity Engine data. No legacy activity history is
backfilled by this revision.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "h7a8b9c0d1e2"
down_revision: str | Sequence[str] | None = "g1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _assert_no_rows(sql: str, message: str) -> None:
    if op.get_bind().execute(sa.text(sql)).scalar_one():
        raise RuntimeError(message)


def _preflight_existing_rows() -> None:
    """Fail without changing data if existing rows cannot satisfy new FKs/checks."""
    checks = (
        (
            """SELECT EXISTS (
                SELECT 1 FROM tasks t LEFT JOIN projects p ON p.id = t.project_id
                WHERE t.project_id IS NOT NULL AND (p.id IS NULL OR t.user_id <> p.user_id)
            )""",
            "Orphaned or cross-user tasks.project_id reference; resolve ownership explicitly before retrying.",
        ),
        (
            """SELECT EXISTS (
                SELECT 1 FROM tasks t LEFT JOIN targets g ON g.id = t.target_id
                WHERE t.target_id IS NOT NULL AND (g.id IS NULL OR t.user_id <> g.user_id)
            )""",
            "Orphaned or cross-user tasks.target_id reference; resolve ownership explicitly before retrying.",
        ),
        (
            """SELECT EXISTS (
                SELECT 1 FROM schedule_items s
                LEFT JOIN tasks t ON t.id = s.task_id
                LEFT JOIN habits h ON h.id = s.habit_id
                LEFT JOIN projects p ON p.id = s.project_id
                LEFT JOIN targets g ON g.id = s.target_id
                WHERE (s.task_id IS NOT NULL AND (t.id IS NULL OR s.user_id <> t.user_id))
                   OR (s.habit_id IS NOT NULL AND (h.id IS NULL OR s.user_id <> h.user_id))
                   OR (s.project_id IS NOT NULL AND (p.id IS NULL OR s.user_id <> p.user_id))
                   OR (s.target_id IS NOT NULL AND (g.id IS NULL OR s.user_id <> g.user_id))
            )""",
            "Invalid or cross-user schedule_items reference; resolve data explicitly before retrying.",
        ),
        (
            """SELECT EXISTS (
                SELECT 1 FROM schedule_items WHERE end_at <= start_at
            )""",
            "Invalid schedule timestamp range; resolve rows explicitly before retrying.",
        ),
        (
            """SELECT EXISTS (
                SELECT 1 FROM time_sessions s
                LEFT JOIN schedule_items b ON b.id = s.schedule_item_id
                LEFT JOIN tasks t ON t.id = s.task_id
                LEFT JOIN habits h ON h.id = s.habit_id
                LEFT JOIN projects p ON p.id = s.project_id
                LEFT JOIN targets g ON g.id = s.target_id
                WHERE (s.schedule_item_id IS NOT NULL AND (b.id IS NULL OR s.user_id <> b.user_id))
                   OR (s.task_id IS NOT NULL AND (t.id IS NULL OR s.user_id <> t.user_id))
                   OR (s.habit_id IS NOT NULL AND (h.id IS NULL OR s.user_id <> h.user_id))
                   OR (s.project_id IS NOT NULL AND (p.id IS NULL OR s.user_id <> p.user_id))
                   OR (s.target_id IS NOT NULL AND (g.id IS NULL OR s.user_id <> g.user_id))
            )""",
            "Invalid or cross-user time_sessions reference; resolve data explicitly before retrying.",
        ),
        (
            """SELECT EXISTS (
                SELECT 1 FROM time_sessions
                WHERE status NOT IN ('running', 'completed', 'cancelled')
                   OR duration_seconds < 0
                   OR NOT (
                     (status = 'running' AND ended_at IS NULL AND duration_seconds IS NULL)
                     OR (status = 'completed' AND ended_at IS NOT NULL AND ended_at > started_at
                         AND duration_seconds IS NOT NULL AND duration_seconds >= 0
                         AND duration_seconds <= floor(extract(epoch FROM (ended_at - started_at))))
                     OR (status = 'cancelled' AND duration_seconds IS NULL
                         AND (ended_at IS NULL OR ended_at > started_at))
                   )
            )""",
            "Incompatible time_sessions status/timestamp/duration row; resolve explicitly before retrying.",
        ),
        (
            """SELECT EXISTS (
                SELECT 1 FROM time_sessions WHERE status = 'running'
                GROUP BY user_id HAVING count(*) > 1
            )""",
            "Multiple running time_sessions exist for one user; resolve explicitly before retrying.",
        ),
    )
    for sql, message in checks:
        _assert_no_rows(sql, message)


def _create_functions_and_triggers() -> None:
    # Use SQLAlchemy text compilation so literal percent placeholders in
    # PostgreSQL RAISE EXCEPTION messages are escaped for the DBAPI correctly.
    op.execute(sa.text("""
        CREATE FUNCTION nexus_check_activity_time_allocations() RETURNS trigger AS $$
        DECLARE
          affected_session_id uuid;
          affected_ids uuid[];
          invalid_session_id uuid;
          activity_duration integer;
          allocated_duration numeric;
        BEGIN
          IF TG_OP = 'INSERT' THEN
            affected_ids := ARRAY(SELECT DISTINCT activity_session_id FROM new_rows
                                  WHERE contribution_type = 'time' ORDER BY activity_session_id);
          ELSIF TG_OP = 'DELETE' THEN
            affected_ids := ARRAY(SELECT DISTINCT activity_session_id FROM old_rows
                                  WHERE contribution_type = 'time' ORDER BY activity_session_id);
          ELSE
            affected_ids := ARRAY(
              SELECT DISTINCT activity_session_id FROM (
                SELECT activity_session_id, contribution_type FROM old_rows
                UNION ALL
                SELECT activity_session_id, contribution_type FROM new_rows
              ) changed WHERE contribution_type = 'time'
              ORDER BY activity_session_id
            );
          END IF;
          PERFORM s.id FROM activity_sessions s
            WHERE s.id = ANY(affected_ids) ORDER BY s.id FOR UPDATE;
          FOREACH affected_session_id IN ARRAY affected_ids LOOP
            IF NOT EXISTS (SELECT 1 FROM activity_sessions WHERE id = affected_session_id) THEN
              -- ON DELETE CASCADE removes contributions after the parent row
              -- has been deleted. That is the only valid missing-parent case:
              -- ordinary INSERT/UPDATE cannot pass their composite FK, and
              -- ordinary DELETEs still validate while their parent exists.
              IF TG_OP = 'DELETE' THEN
                CONTINUE;
              END IF;
              RAISE EXCEPTION 'activity session % does not exist', affected_session_id;
            END IF;
            SELECT duration_seconds INTO activity_duration FROM activity_sessions WHERE id = affected_session_id;
            IF activity_duration IS NULL THEN
              RAISE EXCEPTION 'time allocation requires a credited duration for session %', affected_session_id;
            END IF;
            SELECT COALESCE(SUM(c.contribution_value), 0) INTO allocated_duration
              FROM activity_goal_contributions c
              WHERE c.activity_session_id = affected_session_id AND c.contribution_type = 'time';
            IF allocated_duration > activity_duration THEN
              invalid_session_id := affected_session_id;
              RAISE EXCEPTION 'time allocations exceed activity duration for session %', invalid_session_id;
            END IF;
          END LOOP;
          RETURN NULL;
        END; $$ LANGUAGE plpgsql;
    """))
    op.execute(sa.text("""
        CREATE TRIGGER trg_activity_time_allocation_insert
          AFTER INSERT ON activity_goal_contributions
          REFERENCING NEW TABLE AS new_rows FOR EACH STATEMENT
          EXECUTE FUNCTION nexus_check_activity_time_allocations();
    """))
    op.execute(sa.text("""
        CREATE TRIGGER trg_activity_time_allocation_update
          AFTER UPDATE ON activity_goal_contributions
          REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows FOR EACH STATEMENT
          EXECUTE FUNCTION nexus_check_activity_time_allocations();
    """))
    op.execute(sa.text("""
        CREATE TRIGGER trg_activity_time_allocation_delete
          AFTER DELETE ON activity_goal_contributions
          REFERENCING OLD TABLE AS old_rows FOR EACH STATEMENT
          EXECUTE FUNCTION nexus_check_activity_time_allocations();
    """))
    op.execute(sa.text("""
        CREATE FUNCTION nexus_check_activity_session_duration_change() RETURNS trigger AS $$
        DECLARE
          changed_id uuid;
          allocated_duration numeric;
          changed_duration integer;
        BEGIN
          FOR changed_id IN
            SELECT n.id FROM new_rows n
            JOIN old_rows o ON o.id = n.id
            WHERE n.duration_seconds IS DISTINCT FROM o.duration_seconds
          LOOP
            SELECT duration_seconds INTO changed_duration FROM activity_sessions WHERE id = changed_id;
            SELECT COALESCE(SUM(contribution_value), 0) INTO allocated_duration
              FROM activity_goal_contributions
              WHERE activity_session_id = changed_id AND contribution_type = 'time';
            IF (changed_duration IS NULL AND allocated_duration > 0) OR
               allocated_duration > changed_duration THEN
              RAISE EXCEPTION 'new activity duration is below existing time allocations';
            END IF;
          END LOOP;
          RETURN NULL;
        END; $$ LANGUAGE plpgsql;
    """))
    op.execute(sa.text("""
        CREATE TRIGGER trg_activity_session_duration_allocation_limit
          AFTER UPDATE ON activity_sessions
          REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows FOR EACH STATEMENT
          EXECUTE FUNCTION nexus_check_activity_session_duration_change();
    """))
    op.execute(sa.text("""
        CREATE FUNCTION nexus_check_activity_contribution_target_type() RETURNS trigger AS $$
        DECLARE target_metric text;
        BEGIN
          SELECT metric_type INTO target_metric FROM targets WHERE id = NEW.target_id FOR UPDATE;
          IF NEW.contribution_type = 'time' AND target_metric NOT IN ('time', 'seconds', 'duration') THEN
            RAISE EXCEPTION 'time contribution requires a time target';
          ELSIF NEW.contribution_type = 'metric' AND target_metric IN ('time', 'seconds', 'duration') THEN
            RAISE EXCEPTION 'metric contribution cannot target a time target';
          ELSIF NEW.contribution_type = 'milestone' AND target_metric <> 'milestones_completed' THEN
            RAISE EXCEPTION 'milestone contribution requires a milestone target';
          END IF;
          RETURN NEW;
        END; $$ LANGUAGE plpgsql;
    """))
    op.execute(sa.text("""
        CREATE TRIGGER trg_activity_contribution_target_type
          BEFORE INSERT OR UPDATE OF target_id, contribution_type ON activity_goal_contributions
          FOR EACH ROW EXECUTE FUNCTION nexus_check_activity_contribution_target_type();
    """))
    op.execute(sa.text("""
        CREATE FUNCTION nexus_prevent_incompatible_target_metric_change() RETURNS trigger AS $$
        BEGIN
          IF NEW.metric_type IS DISTINCT FROM OLD.metric_type AND EXISTS (
            SELECT 1 FROM activity_goal_contributions c WHERE c.target_id = OLD.id AND (
              (c.contribution_type = 'time' AND NEW.metric_type NOT IN ('time', 'seconds', 'duration')) OR
              (c.contribution_type = 'metric' AND NEW.metric_type IN ('time', 'seconds', 'duration')) OR
              (c.contribution_type = 'milestone' AND NEW.metric_type <> 'milestones_completed')
            )
          ) THEN
            RAISE EXCEPTION 'target metric type conflicts with existing activity contributions';
          END IF;
          RETURN NEW;
        END; $$ LANGUAGE plpgsql;
    """))
    op.execute(sa.text("""
        CREATE TRIGGER trg_target_metric_type_activity_contributions
          BEFORE UPDATE OF metric_type ON targets
          FOR EACH ROW EXECUTE FUNCTION nexus_prevent_incompatible_target_metric_change();
    """))
    op.execute(sa.text("""
        CREATE FUNCTION nexus_reject_activity_correction_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'activity correction history is immutable';
        END; $$ LANGUAGE plpgsql;
    """))
    op.execute(sa.text("""
        CREATE TRIGGER trg_activity_corrections_immutable
          BEFORE UPDATE OR DELETE ON activity_corrections
          FOR EACH ROW EXECUTE FUNCTION nexus_reject_activity_correction_mutation();
    """))


def _drop_functions_and_triggers() -> None:
    op.execute(sa.text("DROP TRIGGER trg_activity_corrections_immutable ON activity_corrections"))
    op.execute(sa.text("DROP FUNCTION nexus_reject_activity_correction_mutation()"))
    op.execute(sa.text("DROP TRIGGER trg_target_metric_type_activity_contributions ON targets"))
    op.execute(sa.text("DROP FUNCTION nexus_prevent_incompatible_target_metric_change()"))
    op.execute(sa.text("DROP TRIGGER trg_activity_contribution_target_type ON activity_goal_contributions"))
    op.execute(sa.text("DROP FUNCTION nexus_check_activity_contribution_target_type()"))
    op.execute(sa.text("DROP TRIGGER trg_activity_session_duration_allocation_limit ON activity_sessions"))
    op.execute(sa.text("DROP FUNCTION nexus_check_activity_session_duration_change()"))
    op.execute(sa.text("DROP TRIGGER trg_activity_time_allocation_delete ON activity_goal_contributions"))
    op.execute(sa.text("DROP TRIGGER trg_activity_time_allocation_update ON activity_goal_contributions"))
    op.execute(sa.text("DROP TRIGGER trg_activity_time_allocation_insert ON activity_goal_contributions"))
    op.execute(sa.text("DROP FUNCTION nexus_check_activity_time_allocations()"))


def upgrade() -> None:
    _preflight_existing_rows()

    # Parent keys are required targets for composite ownership FKs.
    for table in ("projects", "targets", "habits", "tasks", "schedule_items", "time_sessions"):
        op.create_unique_constraint(f"uq_{table}_id_user_id", table, ["id", "user_id"])

    # Replace legacy single-column nullable references with restrictive
    # same-user references. Explicit target FK names come from their revisions;
    # earlier unnamed FKs use PostgreSQL's documented table_column_fkey name.
    legacy_fks = {
        "tasks": ("tasks_project_id_fkey", "tasks_target_id_fkey"),
        "schedule_items": (
            "schedule_items_task_id_fkey", "schedule_items_habit_id_fkey",
            "schedule_items_project_id_fkey", "fk_schedule_items_target_id_targets",
        ),
        "time_sessions": (
            "fk_time_sessions_target_id_targets", "time_sessions_schedule_item_id_fkey",
            "time_sessions_task_id_fkey", "time_sessions_habit_id_fkey", "time_sessions_project_id_fkey",
        ),
    }
    for table, constraint_names in legacy_fks.items():
        for name in constraint_names:
            op.drop_constraint(name, table, type_="foreignkey")

    ownership_fks = (
        ("tasks", "project_id", "projects", "fk_tasks_project_user"),
        ("tasks", "target_id", "targets", "fk_tasks_target_user"),
        ("schedule_items", "task_id", "tasks", "fk_schedule_items_task_user"),
        ("schedule_items", "habit_id", "habits", "fk_schedule_items_habit_user"),
        ("schedule_items", "project_id", "projects", "fk_schedule_items_project_user"),
        ("schedule_items", "target_id", "targets", "fk_schedule_items_target_user"),
        ("time_sessions", "schedule_item_id", "schedule_items", "fk_time_sessions_schedule_user"),
        ("time_sessions", "task_id", "tasks", "fk_time_sessions_task_user"),
        ("time_sessions", "habit_id", "habits", "fk_time_sessions_habit_user"),
        ("time_sessions", "project_id", "projects", "fk_time_sessions_project_user"),
        ("time_sessions", "target_id", "targets", "fk_time_sessions_target_user"),
    )
    for table, column, parent, name in ownership_fks:
        op.create_foreign_key(
            name, table, parent, [column, "user_id"], ["id", "user_id"]
        )

    op.create_check_constraint("ck_schedule_items_time_range", "schedule_items", "end_at > start_at")
    op.create_check_constraint("ck_time_sessions_status", "time_sessions", "status IN ('running', 'completed', 'cancelled')")
    op.create_check_constraint("ck_time_sessions_duration", "time_sessions", "duration_seconds IS NULL OR duration_seconds >= 0")
    op.create_check_constraint(
        "ck_time_sessions_status_timing", "time_sessions",
        "(status = 'running' AND ended_at IS NULL AND duration_seconds IS NULL) OR "
        "(status = 'completed' AND ended_at IS NOT NULL AND ended_at > started_at "
        "AND duration_seconds IS NOT NULL AND duration_seconds >= 0 AND "
        "duration_seconds <= floor(extract(epoch FROM (ended_at - started_at)))) OR "
        "(status = 'cancelled' AND duration_seconds IS NULL AND (ended_at IS NULL OR ended_at > started_at))",
    )

    # Existing running-session index is preserved; this is the only activity
    # model already represented in legacy tables. All other tables are new.
    op.create_table(
        "activity_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("credential_hash", sa.String(255), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "user_id", name="uq_activity_sources_id_user_id"),
        sa.UniqueConstraint("user_id", "name", name="uq_activity_sources_user_name"),
        sa.UniqueConstraint("credential_hash"),
    )
    op.create_index("ix_activity_sources_user_id", "activity_sources", ["user_id"])
    op.create_index("ix_activity_sources_user_revoked", "activity_sources", ["user_id", "revoked_at"])

    op.create_table(
        "activity_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("external_event_id", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("confidence", sa.Float(), server_default="0.0", nullable=False),
        sa.Column("payload", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id", "user_id"], ["activity_sources.id", "activity_sources.user_id"], ondelete="CASCADE", name="fk_activity_events_source_user"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "external_event_id", name="uq_activity_events_source_external_event"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_activity_events_confidence"),
    )
    op.create_index("ix_activity_events_user_id", "activity_events", ["user_id"])
    op.create_index("ix_activity_events_user_occurred_at", "activity_events", ["user_id", "occurred_at"])
    op.create_index("ix_activity_events_source_occurred_at", "activity_events", ["source_id", "occurred_at"])

    op.create_table(
        "activity_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("time_session_id", sa.Uuid(), nullable=True),
        sa.Column("schedule_item_id", sa.Uuid(), nullable=True),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("habit_id", sa.Uuid(), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Float(), server_default="0.0", nullable=False),
        sa.Column("status", sa.String(16), server_default="draft", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["time_session_id", "user_id"], ["time_sessions.id", "time_sessions.user_id"], name="fk_activity_sessions_time_session_user"),
        sa.ForeignKeyConstraint(["schedule_item_id", "user_id"], ["schedule_items.id", "schedule_items.user_id"], name="fk_activity_sessions_schedule_user"),
        sa.ForeignKeyConstraint(["task_id", "user_id"], ["tasks.id", "tasks.user_id"], name="fk_activity_sessions_task_user"),
        sa.ForeignKeyConstraint(["habit_id", "user_id"], ["habits.id", "habits.user_id"], name="fk_activity_sessions_habit_user"),
        sa.ForeignKeyConstraint(["project_id", "user_id"], ["projects.id", "projects.user_id"], name="fk_activity_sessions_project_user"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "user_id", name="uq_activity_sessions_id_user_id"),
        sa.CheckConstraint("status IN ('draft', 'confirmed', 'corrected', 'discarded')", name="ck_activity_sessions_status"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_activity_sessions_confidence"),
        sa.CheckConstraint("duration_seconds IS NULL OR duration_seconds >= 0", name="ck_activity_sessions_duration"),
        sa.CheckConstraint("ended_at IS NULL OR ended_at > started_at", name="ck_activity_sessions_time_range"),
        sa.CheckConstraint(
            "(status = 'draft' AND ended_at IS NULL AND duration_seconds IS NULL) OR "
            "(status IN ('confirmed', 'corrected') AND ended_at IS NOT NULL AND ended_at > started_at "
            "AND duration_seconds IS NOT NULL AND duration_seconds >= 0 AND "
            "duration_seconds <= floor(extract(epoch FROM (ended_at - started_at)))) OR "
            "(status = 'discarded' AND duration_seconds IS NULL AND (ended_at IS NULL OR ended_at > started_at))",
            name="ck_activity_sessions_status_timing",
        ),
    )
    for column in ("user_id", "time_session_id", "schedule_item_id", "task_id", "habit_id", "project_id"):
        op.create_index(f"ix_activity_sessions_{column}", "activity_sessions", [column])
    op.create_index("uq_activity_sessions_time_session", "activity_sessions", ["time_session_id"], unique=True, postgresql_where=sa.text("time_session_id IS NOT NULL"))
    op.create_index("ix_activity_sessions_user_status_started", "activity_sessions", ["user_id", "status", "started_at"])

    op.create_table(
        "activity_goal_contributions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("activity_session_id", sa.Uuid(), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("contribution_type", sa.String(16), nullable=False),
        sa.Column("contribution_value", sa.Numeric(12, 3), nullable=False),
        sa.Column("unit", sa.String(32), nullable=True),
        sa.Column("details", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["activity_session_id", "user_id"], ["activity_sessions.id", "activity_sessions.user_id"], ondelete="CASCADE", name="fk_activity_goal_contributions_session_user"),
        sa.ForeignKeyConstraint(["target_id", "user_id"], ["targets.id", "targets.user_id"], name="fk_activity_goal_contributions_target_user"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "user_id", name="uq_activity_goal_contributions_id_user_id"),
        sa.CheckConstraint("contribution_type IN ('time', 'metric', 'milestone')", name="ck_activity_goal_contributions_type"),
        sa.CheckConstraint(
            "(contribution_type = 'time' AND contribution_value > 0 AND unit = 'seconds') OR "
            "(contribution_type = 'metric' AND contribution_value >= 0 AND unit IS NOT NULL AND unit <> 'seconds') OR "
            "(contribution_type = 'milestone' AND contribution_value IN (0, 1) AND unit IS NULL)",
            name="ck_activity_goal_contributions_value",
        ),
        sa.CheckConstraint(
            "(contribution_type = 'time' AND unit = 'seconds') OR "
            "(contribution_type = 'metric' AND unit <> 'seconds') OR "
            "(contribution_type = 'milestone' AND unit IS NULL)",
            name="ck_activity_goal_contributions_unit_type",
        ),
    )
    op.create_index("ix_activity_goal_contributions_user_id", "activity_goal_contributions", ["user_id"])
    op.create_index("ix_activity_goal_contributions_target_id", "activity_goal_contributions", ["target_id"])
    op.create_index("uq_activity_goal_contributions_session_target_time", "activity_goal_contributions", ["activity_session_id", "target_id"], unique=True, postgresql_where=sa.text("contribution_type = 'time'"))
    op.create_index("ix_activity_goal_contributions_user_target", "activity_goal_contributions", ["user_id", "target_id"])

    op.create_table(
        "activity_corrections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("activity_session_id", sa.Uuid(), nullable=False),
        sa.Column("field_name", sa.String(64), nullable=False),
        sa.Column("previous_value", postgresql.JSONB(), nullable=False),
        sa.Column("new_value", postgresql.JSONB(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["activity_session_id", "user_id"], ["activity_sessions.id", "activity_sessions.user_id"], ondelete="RESTRICT", name="fk_activity_corrections_session_user"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_activity_corrections_user_id", "activity_corrections", ["user_id"])
    op.create_index("ix_activity_corrections_activity_session_id", "activity_corrections", ["activity_session_id"])

    _create_functions_and_triggers()


def downgrade() -> None:
    # This removes all Activity Engine rows. Corrections are immutable by design;
    # downgrade is therefore destructive and must only be used with an approved
    # backup/recovery plan. This revision intentionally does not restore data.
    _drop_functions_and_triggers()

    op.drop_index("ix_activity_corrections_activity_session_id", table_name="activity_corrections")
    op.drop_index("ix_activity_corrections_user_id", table_name="activity_corrections")
    op.drop_table("activity_corrections")

    op.drop_index("ix_activity_goal_contributions_user_target", table_name="activity_goal_contributions")
    op.drop_index("uq_activity_goal_contributions_session_target_time", table_name="activity_goal_contributions")
    op.drop_index("ix_activity_goal_contributions_target_id", table_name="activity_goal_contributions")
    op.drop_index("ix_activity_goal_contributions_user_id", table_name="activity_goal_contributions")
    op.drop_table("activity_goal_contributions")

    op.drop_index("ix_activity_sessions_user_status_started", table_name="activity_sessions")
    op.drop_index("uq_activity_sessions_time_session", table_name="activity_sessions")
    for column in ("project_id", "habit_id", "task_id", "schedule_item_id", "time_session_id", "user_id"):
        op.drop_index(f"ix_activity_sessions_{column}", table_name="activity_sessions")
    op.drop_table("activity_sessions")

    op.drop_index("ix_activity_events_source_occurred_at", table_name="activity_events")
    op.drop_index("ix_activity_events_user_occurred_at", table_name="activity_events")
    op.drop_index("ix_activity_events_user_id", table_name="activity_events")
    op.drop_table("activity_events")

    op.drop_index("ix_activity_sources_user_revoked", table_name="activity_sources")
    op.drop_index("ix_activity_sources_user_id", table_name="activity_sources")
    op.drop_table("activity_sources")

    op.drop_constraint("ck_time_sessions_status_timing", "time_sessions", type_="check")
    op.drop_constraint("ck_time_sessions_duration", "time_sessions", type_="check")
    op.drop_constraint("ck_time_sessions_status", "time_sessions", type_="check")
    op.drop_constraint("ck_schedule_items_time_range", "schedule_items", type_="check")

    ownership_names = (
        ("time_sessions", "fk_time_sessions_target_user"),
        ("time_sessions", "fk_time_sessions_project_user"),
        ("time_sessions", "fk_time_sessions_habit_user"),
        ("time_sessions", "fk_time_sessions_task_user"),
        ("time_sessions", "fk_time_sessions_schedule_user"),
        ("schedule_items", "fk_schedule_items_target_user"),
        ("schedule_items", "fk_schedule_items_project_user"),
        ("schedule_items", "fk_schedule_items_habit_user"),
        ("schedule_items", "fk_schedule_items_task_user"),
        ("tasks", "fk_tasks_target_user"),
        ("tasks", "fk_tasks_project_user"),
    )
    for table, name in ownership_names:
        op.drop_constraint(name, table, type_="foreignkey")

    # Restore the exact legacy single-column FK definitions and ON DELETE
    # behavior recorded in their original revisions.
    for table, column, parent, name, ondelete in (
        ("tasks", "project_id", "projects", "tasks_project_id_fkey", "SET NULL"),
        ("tasks", "target_id", "targets", "tasks_target_id_fkey", "SET NULL"),
        ("schedule_items", "task_id", "tasks", "schedule_items_task_id_fkey", "SET NULL"),
        ("schedule_items", "habit_id", "habits", "schedule_items_habit_id_fkey", "SET NULL"),
        ("schedule_items", "project_id", "projects", "schedule_items_project_id_fkey", "SET NULL"),
        ("schedule_items", "target_id", "targets", "fk_schedule_items_target_id_targets", "SET NULL"),
        ("time_sessions", "schedule_item_id", "schedule_items", "time_sessions_schedule_item_id_fkey", "SET NULL"),
        ("time_sessions", "task_id", "tasks", "time_sessions_task_id_fkey", "SET NULL"),
        ("time_sessions", "habit_id", "habits", "time_sessions_habit_id_fkey", "SET NULL"),
        ("time_sessions", "project_id", "projects", "time_sessions_project_id_fkey", "SET NULL"),
        ("time_sessions", "target_id", "targets", "fk_time_sessions_target_id_targets", "SET NULL"),
    ):
        op.create_foreign_key(name, table, parent, [column], ["id"], ondelete=ondelete)

    for table in ("time_sessions", "schedule_items", "tasks", "habits", "targets", "projects"):
        op.drop_constraint(f"uq_{table}_id_user_id", table, type_="unique")

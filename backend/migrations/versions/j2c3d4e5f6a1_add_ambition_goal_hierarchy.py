"""add user-controlled ambitions, measured goals and progress history

Revision ID: j2c3d4e5f6a1
Revises: i9b2c4d6e8f0
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "j2c3d4e5f6a1"
down_revision: str | Sequence[str] | None = "i9b2c4d6e8f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ambitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(80), nullable=False),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("priority", sa.Integer(), server_default="3", nullable=False),
        sa.Column("start_date", sa.Date(), server_default=sa.text("CURRENT_DATE"), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column("completed_at", sa.Date(), nullable=True),
        sa.Column("display_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "user_id", name="uq_ambitions_id_user_id"),
        sa.CheckConstraint("status IN ('active', 'paused', 'completed', 'archived')", name="ck_ambitions_status"),
        sa.CheckConstraint("priority BETWEEN 1 AND 5", name="ck_ambitions_priority"),
        sa.CheckConstraint("target_date IS NULL OR target_date >= start_date", name="ck_ambitions_dates"),
    )
    op.create_index("ix_ambitions_user_id", "ambitions", ["user_id"])
    op.create_index("ix_ambitions_user_status_order", "ambitions", ["user_id", "status", "display_order"])

    op.create_table(
        "ambition_lifecycle_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ambition_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("previous_status", sa.String(16), nullable=False),
        sa.Column("new_status", sa.String(16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["ambition_id", "user_id"], ["ambitions.id", "ambitions.user_id"], ondelete="RESTRICT", name="fk_ambition_lifecycle_events_ambition_user"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("previous_status IN ('active', 'paused', 'completed', 'archived')", name="ck_ambition_lifecycle_events_previous"),
        sa.CheckConstraint("new_status IN ('active', 'paused', 'completed', 'archived')", name="ck_ambition_lifecycle_events_new"),
    )
    op.create_index("ix_ambition_lifecycle_events_user_id", "ambition_lifecycle_events", ["user_id"])
    op.create_index("ix_ambition_lifecycle_events_ambition_id", "ambition_lifecycle_events", ["ambition_id"])
    op.create_index("ix_ambition_lifecycle_events_user_ambition_created", "ambition_lifecycle_events", ["user_id", "ambition_id", "created_at"])
    op.execute(sa.text("""
        CREATE FUNCTION nexus_reject_ambition_lifecycle_mutation() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'ambition lifecycle history is append-only'; END; $$ LANGUAGE plpgsql;
        CREATE TRIGGER trg_ambition_lifecycle_immutable BEFORE UPDATE OR DELETE ON ambition_lifecycle_events
          FOR EACH ROW EXECUTE FUNCTION nexus_reject_ambition_lifecycle_mutation();
    """))

    op.create_table(
        "ambition_goals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ambition_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("supporting_project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("priority", sa.Integer(), server_default="3", nullable=False),
        sa.Column("start_date", sa.Date(), server_default=sa.text("CURRENT_DATE"), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column("completed_at", sa.Date(), nullable=True),
        sa.Column("measurement_type", sa.String(24), server_default="count", nullable=False),
        sa.Column("measurement_unit", sa.String(32), nullable=True),
        sa.Column("measurement_definition", sa.Text(), nullable=True),
        sa.Column("target_value", sa.Numeric(16, 4), nullable=True),
        sa.Column("current_value", sa.Numeric(16, 4), server_default="0", nullable=False),
        sa.Column("qualitative_value", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ambition_id", "user_id"], ["ambitions.id", "ambitions.user_id"], ondelete="RESTRICT", name="fk_ambition_goals_ambition_user"),
        sa.ForeignKeyConstraint(["supporting_project_id", "user_id"], ["projects.id", "projects.user_id"], ondelete="RESTRICT", name="fk_ambition_goals_project_user"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "user_id", name="uq_ambition_goals_id_user_id"),
        sa.CheckConstraint("status IN ('active', 'paused', 'completed', 'archived')", name="ck_ambition_goals_status"),
        sa.CheckConstraint("priority BETWEEN 1 AND 5", name="ck_ambition_goals_priority"),
        sa.CheckConstraint("target_date IS NULL OR target_date >= start_date", name="ck_ambition_goals_dates"),
        sa.CheckConstraint("measurement_type IN ('count', 'duration', 'distance', 'weight', 'currency', 'percentage', 'proficiency', 'custom', 'qualitative')", name="ck_ambition_goals_measurement_type"),
    )
    op.create_index("ix_ambition_goals_user_id", "ambition_goals", ["user_id"])
    op.create_index("ix_ambition_goals_ambition_id", "ambition_goals", ["ambition_id"])
    op.create_index("ix_ambition_goals_supporting_project_id", "ambition_goals", ["supporting_project_id"])
    op.create_index("ix_ambition_goals_user_ambition_status", "ambition_goals", ["user_id", "ambition_id", "status"])

    op.create_table(
        "ambition_milestones",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("goal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), server_default="open", nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("completed_at", sa.Date(), nullable=True),
        sa.Column("display_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["goal_id", "user_id"], ["ambition_goals.id", "ambition_goals.user_id"], ondelete="RESTRICT", name="fk_ambition_milestones_goal_user"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("status IN ('open', 'completed', 'cancelled')", name="ck_ambition_milestones_status"),
    )
    op.create_index("ix_ambition_milestones_user_id", "ambition_milestones", ["user_id"])
    op.create_index("ix_ambition_milestones_goal_id", "ambition_milestones", ["goal_id"])
    op.create_index("ix_ambition_milestones_user_goal_order", "ambition_milestones", ["user_id", "goal_id", "display_order"])

    op.create_table(
        "goal_progress_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("goal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("numeric_delta", sa.Numeric(16, 4), nullable=True),
        sa.Column("resulting_value", sa.Numeric(16, 4), nullable=True),
        sa.Column("qualitative_value", sa.Text(), nullable=True),
        sa.Column("unit", sa.String(32), nullable=True),
        sa.Column("source_kind", sa.String(16), server_default="manual", nullable=False),
        sa.Column("source_contribution_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("corrects_entry_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("details", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["goal_id", "user_id"], ["ambition_goals.id", "ambition_goals.user_id"], ondelete="RESTRICT", name="fk_goal_progress_entries_goal_user"),
        sa.ForeignKeyConstraint(["corrects_entry_id", "user_id"], ["goal_progress_entries.id", "goal_progress_entries.user_id"], ondelete="RESTRICT", name="fk_goal_progress_entries_correction_user"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "user_id", name="uq_goal_progress_entries_id_user_id"),
        sa.CheckConstraint("source_kind IN ('manual', 'activity', 'correction', 'milestone')", name="ck_goal_progress_entries_source"),
        sa.CheckConstraint("(numeric_delta IS NOT NULL) OR (qualitative_value IS NOT NULL)", name="ck_goal_progress_entries_value"),
    )
    op.create_index("ix_goal_progress_entries_user_id", "goal_progress_entries", ["user_id"])
    op.create_index("ix_goal_progress_entries_goal_id", "goal_progress_entries", ["goal_id"])
    op.create_index("ix_goal_progress_entries_goal_created", "goal_progress_entries", ["goal_id", "created_at"])
    op.execute(sa.text("""
        CREATE FUNCTION nexus_reject_goal_progress_mutation() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'goal progress history is append-only'; END; $$ LANGUAGE plpgsql;
        CREATE TRIGGER trg_goal_progress_immutable BEFORE UPDATE OR DELETE ON goal_progress_entries
          FOR EACH ROW EXECUTE FUNCTION nexus_reject_goal_progress_mutation();
    """))

    op.add_column("targets", sa.Column("period_type", sa.String(12), server_default="monthly", nullable=False))
    op.add_column("targets", sa.Column("ambition_goal_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_check_constraint("ck_targets_period_type", "targets", "period_type IN ('monthly', 'weekly')")
    op.create_foreign_key("fk_targets_ambition_goal_user", "targets", "ambition_goals", ["ambition_goal_id", "user_id"], ["id", "user_id"])
    op.create_index("ix_targets_ambition_goal_id", "targets", ["ambition_goal_id"])

    op.alter_column("activity_goal_contributions", "target_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True)
    op.add_column("activity_goal_contributions", sa.Column("goal_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("activity_goal_contributions", sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key("fk_activity_goal_contributions_goal_user", "activity_goal_contributions", "ambition_goals", ["goal_id", "user_id"], ["id", "user_id"])
    op.create_check_constraint("ck_activity_goal_contributions_destination", "activity_goal_contributions", "(target_id IS NOT NULL AND goal_id IS NULL) OR (target_id IS NULL AND goal_id IS NOT NULL)")
    op.create_index("ix_activity_goal_contributions_goal_id", "activity_goal_contributions", ["goal_id"])
    op.drop_index("uq_activity_goal_contributions_session_target_time", table_name="activity_goal_contributions")
    op.create_index("uq_activity_goal_contributions_session_target_time", "activity_goal_contributions", ["activity_session_id", "target_id"], unique=True, postgresql_where=sa.text("contribution_type = 'time' AND reversed_at IS NULL"))
    op.create_index("uq_activity_goal_contributions_session_goal_time", "activity_goal_contributions", ["activity_session_id", "goal_id"], unique=True, postgresql_where=sa.text("contribution_type = 'time' AND goal_id IS NOT NULL AND reversed_at IS NULL"))

    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION nexus_check_activity_time_allocations() RETURNS trigger AS $$
        DECLARE affected_session_id uuid; affected_ids uuid[]; invalid_session_id uuid; activity_duration integer; allocated_duration numeric;
        BEGIN
          IF TG_OP = 'INSERT' THEN
            affected_ids := ARRAY(SELECT DISTINCT activity_session_id FROM new_rows WHERE contribution_type='time' ORDER BY activity_session_id);
          ELSIF TG_OP = 'DELETE' THEN
            affected_ids := ARRAY(SELECT DISTINCT activity_session_id FROM old_rows WHERE contribution_type='time' ORDER BY activity_session_id);
          ELSE
            affected_ids := ARRAY(SELECT DISTINCT activity_session_id FROM (
              SELECT activity_session_id, contribution_type FROM old_rows UNION ALL SELECT activity_session_id, contribution_type FROM new_rows
            ) changed WHERE contribution_type='time' ORDER BY activity_session_id);
          END IF;
          PERFORM s.id FROM activity_sessions s WHERE s.id=ANY(affected_ids) ORDER BY s.id FOR UPDATE;
          FOREACH affected_session_id IN ARRAY affected_ids LOOP
            IF NOT EXISTS (SELECT 1 FROM activity_sessions WHERE id=affected_session_id) THEN
              IF TG_OP='DELETE' THEN CONTINUE; END IF;
              RAISE EXCEPTION 'activity session % does not exist', affected_session_id;
            END IF;
            SELECT duration_seconds INTO activity_duration FROM activity_sessions WHERE id=affected_session_id;
            IF activity_duration IS NULL THEN RAISE EXCEPTION 'time allocation requires a credited duration'; END IF;
            SELECT COALESCE(SUM(contribution_value),0) INTO allocated_duration FROM activity_goal_contributions
              WHERE activity_session_id=affected_session_id AND contribution_type='time' AND reversed_at IS NULL;
            IF allocated_duration > activity_duration THEN
              invalid_session_id := affected_session_id;
              RAISE EXCEPTION 'time allocations exceed activity duration for session %', invalid_session_id;
            END IF;
          END LOOP;
          RETURN NULL;
        END; $$ LANGUAGE plpgsql;

        CREATE OR REPLACE FUNCTION nexus_check_activity_session_duration_change() RETURNS trigger AS $$
        DECLARE changed_id uuid; allocated_duration numeric; changed_duration integer;
        BEGIN
          FOR changed_id IN SELECT n.id FROM new_rows n JOIN old_rows o ON o.id=n.id WHERE n.duration_seconds IS DISTINCT FROM o.duration_seconds LOOP
            SELECT duration_seconds INTO changed_duration FROM activity_sessions WHERE id=changed_id;
            SELECT COALESCE(SUM(contribution_value),0) INTO allocated_duration FROM activity_goal_contributions
              WHERE activity_session_id=changed_id AND contribution_type='time' AND reversed_at IS NULL;
            IF (changed_duration IS NULL AND allocated_duration>0) OR allocated_duration>changed_duration THEN
              RAISE EXCEPTION 'new activity duration is below existing time allocations';
            END IF;
          END LOOP;
          RETURN NULL;
        END; $$ LANGUAGE plpgsql;
    """))

    op.execute(sa.text("DROP TRIGGER trg_activity_contribution_target_type ON activity_goal_contributions"))
    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION nexus_check_activity_contribution_target_type() RETURNS trigger AS $$
        DECLARE target_metric text; goal_metric text; goal_unit text;
        BEGIN
          IF NEW.target_id IS NOT NULL THEN
            SELECT metric_type INTO target_metric FROM targets WHERE id = NEW.target_id FOR UPDATE;
            IF NEW.contribution_type = 'time' AND target_metric NOT IN ('time', 'seconds', 'duration') THEN RAISE EXCEPTION 'time contribution requires a time target';
            ELSIF NEW.contribution_type = 'metric' AND target_metric IN ('time', 'seconds', 'duration') THEN RAISE EXCEPTION 'metric contribution cannot target a time target';
            ELSIF NEW.contribution_type = 'milestone' AND target_metric <> 'milestones_completed' THEN RAISE EXCEPTION 'milestone contribution requires a milestone target';
            END IF;
          ELSE
            SELECT measurement_type, measurement_unit INTO goal_metric, goal_unit FROM ambition_goals WHERE id = NEW.goal_id FOR UPDATE;
            IF NEW.contribution_type = 'time' AND (goal_metric <> 'duration' OR NEW.unit <> 'seconds') THEN RAISE EXCEPTION 'time contribution requires a duration goal measured in seconds';
            ELSIF NEW.contribution_type = 'metric' AND (goal_metric IN ('duration', 'qualitative') OR NEW.unit IS DISTINCT FROM goal_unit) THEN RAISE EXCEPTION 'metric contribution unit must match its ambition goal';
            ELSIF NEW.contribution_type = 'milestone' AND (goal_metric <> 'count' OR NEW.contribution_value NOT IN (0, 1) OR NEW.unit IS NOT NULL) THEN RAISE EXCEPTION 'milestone contribution requires a count goal and value 0 or 1';
            END IF;
          END IF;
          RETURN NEW;
        END; $$ LANGUAGE plpgsql;
        CREATE TRIGGER trg_activity_contribution_target_type BEFORE INSERT OR UPDATE OF target_id, goal_id, contribution_type, unit
          ON activity_goal_contributions FOR EACH ROW EXECUTE FUNCTION nexus_check_activity_contribution_target_type();

        CREATE FUNCTION nexus_prevent_incompatible_ambition_goal_measurement_change() RETURNS trigger AS $$
        BEGIN
          IF (NEW.measurement_type IS DISTINCT FROM OLD.measurement_type OR NEW.measurement_unit IS DISTINCT FROM OLD.measurement_unit)
             AND EXISTS (SELECT 1 FROM activity_goal_contributions c WHERE c.goal_id=OLD.id AND (
               (c.contribution_type='time' AND (NEW.measurement_type <> 'duration' OR c.unit <> 'seconds')) OR
               (c.contribution_type='metric' AND (NEW.measurement_type IN ('duration','qualitative') OR c.unit IS DISTINCT FROM NEW.measurement_unit)))) THEN
            RAISE EXCEPTION 'ambition goal measurement conflicts with existing contributions';
          END IF;
          RETURN NEW;
        END; $$ LANGUAGE plpgsql;
        CREATE TRIGGER trg_ambition_goal_measurement_activity_contributions BEFORE UPDATE OF measurement_type, measurement_unit
          ON ambition_goals FOR EACH ROW EXECUTE FUNCTION nexus_prevent_incompatible_ambition_goal_measurement_change();
    """))


def downgrade() -> None:
    bind = op.get_bind()
    has_data = bind.execute(sa.text("""
        SELECT EXISTS (SELECT 1 FROM ambitions) OR EXISTS (SELECT 1 FROM ambition_goals)
          OR EXISTS (SELECT 1 FROM ambition_lifecycle_events)
          OR EXISTS (SELECT 1 FROM ambition_milestones) OR EXISTS (SELECT 1 FROM goal_progress_entries)
          OR EXISTS (SELECT 1 FROM targets WHERE ambition_goal_id IS NOT NULL)
          OR EXISTS (SELECT 1 FROM activity_goal_contributions WHERE goal_id IS NOT NULL)
          OR EXISTS (SELECT 1 FROM activity_goal_contributions WHERE reversed_at IS NOT NULL)
    """)).scalar_one()
    if has_data:
        raise RuntimeError("Cannot downgrade: ambition or goal history exists.")

    op.execute(sa.text("DROP TRIGGER trg_ambition_goal_measurement_activity_contributions ON ambition_goals"))
    op.execute(sa.text("DROP FUNCTION nexus_prevent_incompatible_ambition_goal_measurement_change()"))
    op.execute(sa.text("DROP TRIGGER trg_activity_contribution_target_type ON activity_goal_contributions"))
    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION nexus_check_activity_contribution_target_type() RETURNS trigger AS $$
        DECLARE target_metric text;
        BEGIN
          SELECT metric_type INTO target_metric FROM targets WHERE id = NEW.target_id FOR UPDATE;
          IF NEW.contribution_type = 'time' AND target_metric NOT IN ('time', 'seconds', 'duration') THEN RAISE EXCEPTION 'time contribution requires a time target';
          ELSIF NEW.contribution_type = 'metric' AND target_metric IN ('time', 'seconds', 'duration') THEN RAISE EXCEPTION 'metric contribution cannot target a time target';
          ELSIF NEW.contribution_type = 'milestone' AND target_metric <> 'milestones_completed' THEN RAISE EXCEPTION 'milestone contribution requires a milestone target';
          END IF;
          RETURN NEW;
        END; $$ LANGUAGE plpgsql;
        CREATE TRIGGER trg_activity_contribution_target_type BEFORE INSERT OR UPDATE OF target_id, contribution_type
          ON activity_goal_contributions FOR EACH ROW EXECUTE FUNCTION nexus_check_activity_contribution_target_type();
    """))
    op.drop_index("uq_activity_goal_contributions_session_goal_time", table_name="activity_goal_contributions")
    op.drop_index("ix_activity_goal_contributions_goal_id", table_name="activity_goal_contributions")
    op.drop_index("uq_activity_goal_contributions_session_target_time", table_name="activity_goal_contributions")
    op.create_index("uq_activity_goal_contributions_session_target_time", "activity_goal_contributions", ["activity_session_id", "target_id"], unique=True, postgresql_where=sa.text("contribution_type = 'time'"))
    op.drop_constraint("ck_activity_goal_contributions_destination", "activity_goal_contributions", type_="check")
    op.drop_constraint("fk_activity_goal_contributions_goal_user", "activity_goal_contributions", type_="foreignkey")
    op.drop_column("activity_goal_contributions", "goal_id")
    op.drop_column("activity_goal_contributions", "reversed_at")
    op.alter_column("activity_goal_contributions", "target_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False)
    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION nexus_check_activity_time_allocations() RETURNS trigger AS $$
        DECLARE affected_session_id uuid; affected_ids uuid[]; invalid_session_id uuid; activity_duration integer; allocated_duration numeric;
        BEGIN
          IF TG_OP='INSERT' THEN
            affected_ids := ARRAY(SELECT DISTINCT activity_session_id FROM new_rows WHERE contribution_type='time' ORDER BY activity_session_id);
          ELSIF TG_OP='DELETE' THEN
            affected_ids := ARRAY(SELECT DISTINCT activity_session_id FROM old_rows WHERE contribution_type='time' ORDER BY activity_session_id);
          ELSE
            affected_ids := ARRAY(SELECT DISTINCT activity_session_id FROM (
              SELECT activity_session_id, contribution_type FROM old_rows UNION ALL SELECT activity_session_id, contribution_type FROM new_rows
            ) changed WHERE contribution_type='time' ORDER BY activity_session_id);
          END IF;
          PERFORM s.id FROM activity_sessions s WHERE s.id=ANY(affected_ids) ORDER BY s.id FOR UPDATE;
          FOREACH affected_session_id IN ARRAY affected_ids LOOP
            IF NOT EXISTS (SELECT 1 FROM activity_sessions WHERE id=affected_session_id) THEN
              IF TG_OP='DELETE' THEN CONTINUE; END IF;
              RAISE EXCEPTION 'activity session % does not exist', affected_session_id;
            END IF;
            SELECT duration_seconds INTO activity_duration FROM activity_sessions WHERE id=affected_session_id;
            IF activity_duration IS NULL THEN RAISE EXCEPTION 'time allocation requires a credited duration'; END IF;
            SELECT COALESCE(SUM(contribution_value),0) INTO allocated_duration FROM activity_goal_contributions
              WHERE activity_session_id=affected_session_id AND contribution_type='time';
            IF allocated_duration > activity_duration THEN
              invalid_session_id := affected_session_id;
              RAISE EXCEPTION 'time allocations exceed activity duration for session %', invalid_session_id;
            END IF;
          END LOOP;
          RETURN NULL;
        END; $$ LANGUAGE plpgsql;
        CREATE OR REPLACE FUNCTION nexus_check_activity_session_duration_change() RETURNS trigger AS $$
        DECLARE changed_id uuid; allocated_duration numeric; changed_duration integer;
        BEGIN
          FOR changed_id IN SELECT n.id FROM new_rows n JOIN old_rows o ON o.id=n.id WHERE n.duration_seconds IS DISTINCT FROM o.duration_seconds LOOP
            SELECT duration_seconds INTO changed_duration FROM activity_sessions WHERE id=changed_id;
            SELECT COALESCE(SUM(contribution_value),0) INTO allocated_duration FROM activity_goal_contributions
              WHERE activity_session_id=changed_id AND contribution_type='time';
            IF (changed_duration IS NULL AND allocated_duration>0) OR allocated_duration>changed_duration THEN
              RAISE EXCEPTION 'new activity duration is below existing time allocations';
            END IF;
          END LOOP;
          RETURN NULL;
        END; $$ LANGUAGE plpgsql;
    """))
    op.drop_index("ix_targets_ambition_goal_id", table_name="targets")
    op.drop_constraint("fk_targets_ambition_goal_user", "targets", type_="foreignkey")
    op.drop_constraint("ck_targets_period_type", "targets", type_="check")
    op.drop_column("targets", "ambition_goal_id")
    op.drop_column("targets", "period_type")
    op.execute(sa.text("DROP TRIGGER trg_goal_progress_immutable ON goal_progress_entries"))
    op.execute(sa.text("DROP FUNCTION nexus_reject_goal_progress_mutation()"))
    op.drop_index("ix_goal_progress_entries_goal_created", table_name="goal_progress_entries")
    op.drop_index("ix_goal_progress_entries_goal_id", table_name="goal_progress_entries")
    op.drop_index("ix_goal_progress_entries_user_id", table_name="goal_progress_entries")
    op.drop_table("goal_progress_entries")
    op.execute(sa.text("DROP TRIGGER trg_ambition_lifecycle_immutable ON ambition_lifecycle_events"))
    op.execute(sa.text("DROP FUNCTION nexus_reject_ambition_lifecycle_mutation()"))
    op.drop_index("ix_ambition_lifecycle_events_user_ambition_created", table_name="ambition_lifecycle_events")
    op.drop_index("ix_ambition_lifecycle_events_ambition_id", table_name="ambition_lifecycle_events")
    op.drop_index("ix_ambition_lifecycle_events_user_id", table_name="ambition_lifecycle_events")
    op.drop_table("ambition_lifecycle_events")
    op.drop_index("ix_ambition_milestones_user_goal_order", table_name="ambition_milestones")
    op.drop_index("ix_ambition_milestones_goal_id", table_name="ambition_milestones")
    op.drop_index("ix_ambition_milestones_user_id", table_name="ambition_milestones")
    op.drop_table("ambition_milestones")
    op.drop_index("ix_ambition_goals_user_ambition_status", table_name="ambition_goals")
    op.drop_index("ix_ambition_goals_supporting_project_id", table_name="ambition_goals")
    op.drop_index("ix_ambition_goals_ambition_id", table_name="ambition_goals")
    op.drop_index("ix_ambition_goals_user_id", table_name="ambition_goals")
    op.drop_table("ambition_goals")
    op.drop_index("ix_ambitions_user_status_order", table_name="ambitions")
    op.drop_index("ix_ambitions_user_id", table_name="ambitions")
    op.drop_table("ambitions")

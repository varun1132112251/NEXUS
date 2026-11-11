from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy import DDL, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class ActivityGoalContribution(Base):
    """A typed goal contribution; a session may allocate time to many goals."""

    __tablename__ = "activity_goal_contributions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["activity_session_id", "user_id"],
            ["activity_sessions.id", "activity_sessions.user_id"],
            ondelete="CASCADE",
            name="fk_activity_goal_contributions_session_user",
        ),
        ForeignKeyConstraint(
            ["target_id", "user_id"], ["targets.id", "targets.user_id"],
            name="fk_activity_goal_contributions_target_user",
        ),
        UniqueConstraint("id", "user_id", name="uq_activity_goal_contributions_id_user_id"),
        CheckConstraint(
            "contribution_type IN ('time', 'metric', 'milestone')",
            name="ck_activity_goal_contributions_type",
        ),
        CheckConstraint(
            "(contribution_type = 'time' AND contribution_value > 0 AND unit = 'seconds') OR (contribution_type = 'metric' AND contribution_value >= 0 AND unit IS NOT NULL AND unit <> 'seconds') OR (contribution_type = 'milestone' AND contribution_value IN (0, 1) AND unit IS NULL)",
            name="ck_activity_goal_contributions_value",
        ),
        CheckConstraint(
            "(contribution_type = 'time' AND unit = 'seconds') OR "
            "(contribution_type = 'metric' AND unit <> 'seconds') OR "
            "(contribution_type = 'milestone' AND unit IS NULL)",
            name="ck_activity_goal_contributions_unit_type",
        ),
        Index(
            "uq_activity_goal_contributions_session_target_time",
            "activity_session_id",
            "target_id",
            unique=True,
            postgresql_where=text("contribution_type = 'time'"),
        ),
        Index(
            "ix_activity_goal_contributions_user_target",
            "user_id",
            "target_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    activity_session_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    target_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, index=True
    )
    contribution_type: Mapped[str] = mapped_column(String(16), nullable=False)
    contribution_value: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    details: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=text("CURRENT_TIMESTAMP")
    )


_allocation_trigger = DDL("""
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

  -- Acquire every affected parent lock in globally deterministic order. These
  -- locks serialize statements for each session under READ COMMITTED.
  PERFORM s.id FROM activity_sessions s
    WHERE s.id = ANY(affected_ids) ORDER BY s.id FOR UPDATE;

  FOREACH affected_session_id IN ARRAY affected_ids LOOP
    IF NOT EXISTS (SELECT 1 FROM activity_sessions WHERE id = affected_session_id) THEN
      RAISE EXCEPTION 'activity session %% does not exist', affected_session_id;
    END IF;
    SELECT duration_seconds INTO activity_duration FROM activity_sessions WHERE id = affected_session_id;
    IF activity_duration IS NULL THEN
      RAISE EXCEPTION 'time allocation requires a credited duration for session %%', affected_session_id;
    END IF;
    SELECT COALESCE(SUM(c.contribution_value), 0) INTO allocated_duration
      FROM activity_goal_contributions c
      WHERE c.activity_session_id = affected_session_id AND c.contribution_type = 'time';
    IF allocated_duration > activity_duration THEN
      invalid_session_id := affected_session_id;
      RAISE EXCEPTION 'time allocations exceed activity duration for session %%', invalid_session_id;
    END IF;
  END LOOP;
  RETURN NULL;
END; $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_activity_time_allocation_insert
  AFTER INSERT ON activity_goal_contributions
  REFERENCING NEW TABLE AS new_rows FOR EACH STATEMENT
  EXECUTE FUNCTION nexus_check_activity_time_allocations();
CREATE TRIGGER trg_activity_time_allocation_update
  AFTER UPDATE ON activity_goal_contributions
  REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows FOR EACH STATEMENT
  EXECUTE FUNCTION nexus_check_activity_time_allocations();
CREATE TRIGGER trg_activity_time_allocation_delete
  AFTER DELETE ON activity_goal_contributions
  REFERENCING OLD TABLE AS old_rows FOR EACH STATEMENT
  EXECUTE FUNCTION nexus_check_activity_time_allocations();

CREATE FUNCTION nexus_check_activity_session_duration_change() RETURNS trigger AS $$
DECLARE changed_id uuid;
DECLARE allocated_duration numeric;
DECLARE changed_duration integer;
BEGIN
  FOR changed_id IN SELECT id FROM new_rows WHERE duration_seconds IS DISTINCT FROM
      (SELECT duration_seconds FROM old_rows WHERE old_rows.id = new_rows.id)
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
CREATE TRIGGER trg_activity_session_duration_allocation_limit
  AFTER UPDATE ON activity_sessions
  REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows FOR EACH STATEMENT
  EXECUTE FUNCTION nexus_check_activity_session_duration_change();
""")

event.listen(ActivityGoalContribution.__table__, "after_create", _allocation_trigger)

_target_type_trigger = DDL("""
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
CREATE TRIGGER trg_activity_contribution_target_type
  BEFORE INSERT OR UPDATE OF target_id, contribution_type ON activity_goal_contributions
  FOR EACH ROW EXECUTE FUNCTION nexus_check_activity_contribution_target_type();

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
CREATE TRIGGER trg_target_metric_type_activity_contributions
  BEFORE UPDATE OF metric_type ON targets
  FOR EACH ROW EXECUTE FUNCTION nexus_prevent_incompatible_target_metric_change();
""")
event.listen(ActivityGoalContribution.__table__, "after_create", _target_type_trigger)

event.listen(
    ActivityGoalContribution.__table__,
    "before_drop",
    DDL("""
    DROP TRIGGER IF EXISTS trg_activity_time_allocation_insert ON activity_goal_contributions;
    DROP TRIGGER IF EXISTS trg_activity_time_allocation_update ON activity_goal_contributions;
    DROP TRIGGER IF EXISTS trg_activity_time_allocation_delete ON activity_goal_contributions;
    DROP TRIGGER IF EXISTS trg_activity_contribution_target_type ON activity_goal_contributions;
    DROP TRIGGER IF EXISTS trg_activity_session_duration_allocation_limit ON activity_sessions;
    DROP TRIGGER IF EXISTS trg_target_metric_type_activity_contributions ON targets;
    DROP FUNCTION IF EXISTS nexus_check_activity_time_allocations();
    DROP FUNCTION IF EXISTS nexus_check_activity_session_duration_change();
    DROP FUNCTION IF EXISTS nexus_check_activity_contribution_target_type();
    DROP FUNCTION IF EXISTS nexus_prevent_incompatible_target_metric_change();
    """),
)

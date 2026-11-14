"""add activity evidence provenance and stopwatch pause segments

Revision ID: i9b2c4d6e8f0
Revises: h7a8b9c0d1e2
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "i9b2c4d6e8f0"
down_revision: str | Sequence[str] | None = "h7a8b9c0d1e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT EXISTS (SELECT 1 FROM time_sessions WHERE status = 'running' GROUP BY user_id HAVING count(*) > 1)")).scalar_one():
        raise RuntimeError("Cannot upgrade: multiple running timers exist for a user; resolve explicitly first.")
    if bind.execute(sa.text("SELECT EXISTS (SELECT 1 FROM activity_records WHERE id IS NULL OR user_id IS NULL)")).scalar_one():
        raise RuntimeError("Cannot upgrade: activity_records contains rows without stable ownership.")
    op.create_unique_constraint("uq_activity_records_id_user_id", "activity_records", ["id", "user_id"])
    op.alter_column("activity_goal_contributions", "activity_session_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True)
    op.add_column("activity_goal_contributions", sa.Column("activity_record_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.drop_constraint("fk_activity_goal_contributions_session_user", "activity_goal_contributions", type_="foreignkey")
    op.create_foreign_key(
        "fk_activity_goal_contributions_session_user", "activity_goal_contributions", "activity_sessions",
        ["activity_session_id", "user_id"], ["id", "user_id"], ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_activity_goal_contributions_record_user", "activity_goal_contributions", "activity_records",
        ["activity_record_id", "user_id"], ["id", "user_id"], ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_activity_goal_contributions_source", "activity_goal_contributions",
        "((activity_session_id IS NOT NULL AND activity_record_id IS NULL) OR "
        "(activity_session_id IS NULL AND activity_record_id IS NOT NULL)) AND "
        "(contribution_type <> 'time' OR activity_session_id IS NOT NULL)",
    )
    op.create_index("ix_activity_goal_contributions_activity_record_id", "activity_goal_contributions", ["activity_record_id"])
    op.add_column("activity_events", sa.Column("discarded_at", sa.DateTime(timezone=True), nullable=True))
    op.create_unique_constraint("uq_activity_events_id_user_id", "activity_events", ["id", "user_id"])
    op.add_column("activity_sessions", sa.Column("source_kind", sa.String(length=16), server_default="legacy", nullable=False))
    op.drop_constraint("ck_activity_sessions_status", "activity_sessions", type_="check")
    op.create_check_constraint("ck_activity_sessions_status", "activity_sessions", "status IN ('draft', 'confirmed', 'corrected', 'discarded', 'superseded')")
    op.drop_constraint("ck_activity_sessions_status_timing", "activity_sessions", type_="check")
    op.create_check_constraint(
        "ck_activity_sessions_status_timing", "activity_sessions",
        "(status = 'draft' AND ((ended_at IS NULL AND duration_seconds IS NULL) OR "
        "(ended_at IS NOT NULL AND ended_at > started_at AND duration_seconds IS NOT NULL AND duration_seconds >= 0 AND duration_seconds <= floor(extract(epoch FROM (ended_at - started_at)))))) OR "
        "(status IN ('confirmed', 'corrected') AND ended_at IS NOT NULL AND ended_at > started_at AND duration_seconds IS NOT NULL AND duration_seconds >= 0 AND duration_seconds <= floor(extract(epoch FROM (ended_at - started_at)))) OR "
        "(status IN ('discarded', 'superseded') AND (duration_seconds IS NULL OR "
        "(ended_at IS NOT NULL AND ended_at > started_at AND duration_seconds >= 0 AND duration_seconds <= floor(extract(epoch FROM (ended_at - started_at))))))",
    )
    op.create_check_constraint("ck_activity_sessions_source_kind", "activity_sessions", "source_kind IN ('observed', 'manual', 'stopwatch', 'merged', 'legacy')")

    op.create_table(
        "activity_session_events",
        sa.Column("activity_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("activity_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=24), server_default="evidence", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["activity_session_id", "user_id"], ["activity_sessions.id", "activity_sessions.user_id"], name="fk_activity_session_events_session_user", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["activity_event_id", "user_id"], ["activity_events.id", "activity_events.user_id"], name="fk_activity_session_events_event_user", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("activity_session_id", "activity_event_id", name="pk_activity_session_events"),
    )
    op.create_index("ix_activity_session_events_user_id", "activity_session_events", ["user_id"])
    op.create_index("ix_activity_session_events_activity_event_id", "activity_session_events", ["activity_event_id"])
    op.create_table(
        "activity_session_lineage",
        sa.Column("parent_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("child_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operation", sa.String(length=12), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_session_id", "user_id"], ["activity_sessions.id", "activity_sessions.user_id"], name="fk_activity_session_lineage_parent_user", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["child_session_id", "user_id"], ["activity_sessions.id", "activity_sessions.user_id"], name="fk_activity_session_lineage_child_user", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("parent_session_id", "child_session_id"),
    )
    op.create_index("ix_activity_session_lineage_user_id", "activity_session_lineage", ["user_id"])

    # Replace the running-only guards while retaining an existing running timer.
    op.drop_index("uq_time_sessions_one_running_per_user", table_name="time_sessions")
    op.drop_constraint("ck_time_sessions_status", "time_sessions", type_="check")
    op.drop_constraint("ck_time_sessions_status_timing", "time_sessions", type_="check")
    op.create_check_constraint("ck_time_sessions_status", "time_sessions", "status IN ('running', 'paused', 'completed', 'cancelled')")
    op.create_check_constraint(
        "ck_time_sessions_status_timing", "time_sessions",
        "(status = 'running' AND ended_at IS NULL AND duration_seconds IS NULL) OR "
        "(status = 'paused' AND ended_at IS NULL AND duration_seconds IS NOT NULL AND duration_seconds >= 0) OR "
        "(status = 'completed' AND ended_at IS NOT NULL AND ended_at > started_at AND duration_seconds IS NOT NULL AND duration_seconds >= 0 AND duration_seconds <= floor(extract(epoch FROM (ended_at - started_at)))) OR "
        "(status = 'cancelled' AND duration_seconds IS NULL AND (ended_at IS NULL OR ended_at > started_at))",
    )
    op.create_index("uq_time_sessions_one_running_per_user", "time_sessions", ["user_id"], unique=True, postgresql_where=sa.text("status IN ('running', 'paused')"))
    op.create_table(
        "time_session_segments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("time_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("ended_at IS NULL OR ended_at > started_at", name="ck_time_session_segments_range"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["time_session_id", "user_id"], ["time_sessions.id", "time_sessions.user_id"], name="fk_time_session_segments_session_user", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_time_session_segments_time_session_id", "time_session_segments", ["time_session_id"])
    op.create_index("ix_time_session_segments_user_id", "time_session_segments", ["user_id"])
    op.create_index("uq_time_session_segments_one_open", "time_session_segments", ["time_session_id"], unique=True, postgresql_where=sa.text("ended_at IS NULL"))
    op.execute(sa.text("""
        INSERT INTO time_session_segments(id, time_session_id, user_id, started_at)
        SELECT gen_random_uuid(), id, user_id, started_at FROM time_sessions WHERE status = 'running'
    """))


def downgrade() -> None:
    bind = op.get_bind()
    new_data = bind.execute(sa.text("""
        SELECT
          EXISTS (SELECT 1 FROM activity_session_events) AS evidence,
          EXISTS (SELECT 1 FROM activity_session_lineage) AS lineage,
          EXISTS (SELECT 1 FROM activity_corrections) AS corrections,
          EXISTS (SELECT 1 FROM activity_goal_contributions) AS contributions,
          EXISTS (SELECT 1 FROM activity_sessions WHERE source_kind <> 'legacy') AS nonlegacy_sessions,
          EXISTS (SELECT 1 FROM activity_sessions WHERE status = 'superseded') AS superseded_sessions,
          EXISTS (SELECT 1 FROM activity_sessions WHERE status = 'discarded' AND duration_seconds IS NOT NULL) AS retained_discarded,
          EXISTS (SELECT 1 FROM activity_events WHERE discarded_at IS NOT NULL) AS discarded_events,
          EXISTS (SELECT 1 FROM time_sessions WHERE status = 'paused') AS paused_timers,
          EXISTS (SELECT 1 FROM time_session_segments s JOIN time_sessions t ON t.id=s.time_session_id
                  WHERE t.status <> 'running' OR s.ended_at IS NOT NULL OR s.started_at <> t.started_at) AS changed_segments
    """)).mappings().one()
    if any(new_data.values()):
        raise RuntimeError("Cannot downgrade: new activity provenance or paused stopwatch data exists: " + ", ".join(name for name, present in new_data.items() if present) + ".")
    has_record_contributions = bind.execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM activity_goal_contributions WHERE activity_record_id IS NOT NULL)"
    )).scalar_one()
    if has_record_contributions or bind.execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM activity_goal_contributions)"
    )).scalar_one():
        raise RuntimeError("Cannot downgrade: activity contribution ledger data exists; legacy downgrade would remove it.")

    op.drop_index("uq_time_session_segments_one_open", table_name="time_session_segments")
    op.drop_index("ix_time_session_segments_user_id", table_name="time_session_segments")
    op.drop_index("ix_time_session_segments_time_session_id", table_name="time_session_segments")
    op.drop_table("time_session_segments")
    op.drop_index("ix_activity_goal_contributions_activity_record_id", table_name="activity_goal_contributions")
    op.drop_constraint("ck_activity_goal_contributions_source", "activity_goal_contributions", type_="check")
    op.drop_constraint("fk_activity_goal_contributions_record_user", "activity_goal_contributions", type_="foreignkey")
    op.drop_column("activity_goal_contributions", "activity_record_id")
    op.drop_constraint("fk_activity_goal_contributions_session_user", "activity_goal_contributions", type_="foreignkey")
    op.create_foreign_key(
        "fk_activity_goal_contributions_session_user", "activity_goal_contributions", "activity_sessions",
        ["activity_session_id", "user_id"], ["id", "user_id"], ondelete="CASCADE",
    )
    op.alter_column("activity_goal_contributions", "activity_session_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False)
    op.drop_constraint("uq_activity_records_id_user_id", "activity_records", type_="unique")
    op.drop_index("uq_time_sessions_one_running_per_user", table_name="time_sessions")
    op.drop_constraint("ck_time_sessions_status_timing", "time_sessions", type_="check")
    op.drop_constraint("ck_time_sessions_status", "time_sessions", type_="check")
    op.create_check_constraint("ck_time_sessions_status", "time_sessions", "status IN ('running', 'completed', 'cancelled')")
    op.create_check_constraint(
        "ck_time_sessions_status_timing", "time_sessions",
        "(status = 'running' AND ended_at IS NULL AND duration_seconds IS NULL) OR "
        "(status = 'completed' AND ended_at IS NOT NULL AND ended_at > started_at AND duration_seconds IS NOT NULL AND duration_seconds >= 0 AND duration_seconds <= floor(extract(epoch FROM (ended_at - started_at)))) OR "
        "(status = 'cancelled' AND duration_seconds IS NULL AND (ended_at IS NULL OR ended_at > started_at))",
    )
    op.create_index("uq_time_sessions_one_running_per_user", "time_sessions", ["user_id"], unique=True, postgresql_where=sa.text("status = 'running'"))
    op.drop_index("ix_activity_session_lineage_user_id", table_name="activity_session_lineage")
    op.drop_table("activity_session_lineage")
    op.drop_index("ix_activity_session_events_activity_event_id", table_name="activity_session_events")
    op.drop_index("ix_activity_session_events_user_id", table_name="activity_session_events")
    op.drop_table("activity_session_events")
    op.drop_constraint("ck_activity_sessions_source_kind", "activity_sessions", type_="check")
    op.drop_column("activity_sessions", "source_kind")
    op.drop_constraint("ck_activity_sessions_status", "activity_sessions", type_="check")
    op.create_check_constraint("ck_activity_sessions_status", "activity_sessions", "status IN ('draft', 'confirmed', 'corrected', 'discarded')")
    op.drop_constraint("ck_activity_sessions_status_timing", "activity_sessions", type_="check")
    op.create_check_constraint(
        "ck_activity_sessions_status_timing", "activity_sessions",
        "(status = 'draft' AND ended_at IS NULL AND duration_seconds IS NULL) OR "
        "(status IN ('confirmed', 'corrected') AND ended_at IS NOT NULL AND ended_at > started_at AND duration_seconds IS NOT NULL AND duration_seconds >= 0 AND duration_seconds <= floor(extract(epoch FROM (ended_at - started_at)))) OR "
        "(status = 'discarded' AND duration_seconds IS NULL AND (ended_at IS NULL OR ended_at > started_at))",
    )
    op.drop_constraint("uq_activity_events_id_user_id", "activity_events", type_="unique")
    op.drop_column("activity_events", "discarded_at")

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB

from app.models import (
    ActivityCorrection,
    ActivityEvent,
    ActivityGoalContribution,
    ActivitySession,
    ActivitySource,
)
from app.models.activity_goal_contribution import _allocation_trigger


def test_allocation_trigger_ddl_compiles_with_postgresql_percent_placeholders() -> None:
    compiled = str(_allocation_trigger.compile(dialect=postgresql.dialect()))

    assert compiled.count("session %%") == 3


def test_activity_engine_models_are_registered() -> None:
    assert {
        "activity_sources",
        "activity_events",
        "activity_sessions",
        "activity_goal_contributions",
        "activity_corrections",
    }.issubset(ActivitySource.metadata.tables)


def test_activity_source_has_revocation_and_hashed_credentials() -> None:
    assert "revoked_at" in ActivitySource.__table__.c
    assert "credential_hash" in ActivitySource.__table__.c
    assert ActivitySource.__table__.c.credential_hash.unique is True


def test_activity_event_is_idempotent_per_source_and_external_event() -> None:
    unique_constraints = {
        tuple(column.name for column in constraint.columns)
        for constraint in ActivityEvent.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert ("source_id", "external_event_id") in unique_constraints
    assert isinstance(ActivityEvent.__table__.c.payload.type, JSONB)

    event_fks = [
        constraint for constraint in ActivityEvent.__table__.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    ]
    assert any(tuple(column.name for column in fk.columns) == ("source_id", "user_id") for fk in event_fks)


def test_activity_session_has_validated_states_confidence_and_duration() -> None:
    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in ActivitySession.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert "ck_activity_sessions_status" in checks
    assert all(
        state in checks["ck_activity_sessions_status"]
        for state in ("draft", "confirmed", "corrected", "discarded")
    )
    assert "ck_activity_sessions_confidence" in checks
    assert "ck_activity_sessions_duration" in checks
    assert "duration_seconds = floor" not in checks["ck_activity_sessions_status_timing"]
    assert "duration_seconds <= floor" in checks["ck_activity_sessions_status_timing"]
    for column in (
        "time_session_id",
        "schedule_item_id",
        "task_id",
        "habit_id",
        "project_id",
    ):
        assert column in ActivitySession.__table__.c
    time_session_indexes = [
        index
        for index in ActivitySession.__table__.indexes
        if index.name == "uq_activity_sessions_time_session"
    ]
    assert len(time_session_indexes) == 1
    assert time_session_indexes[0].unique is True
    assert "IS NOT NULL" in str(
        time_session_indexes[0].dialect_options["postgresql"]["where"]
    )


def test_goal_contributions_are_typed_nonnegative_and_do_not_duplicate_time() -> None:
    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in ActivityGoalContribution.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }
    time_indexes = [
        index
        for index in ActivityGoalContribution.__table__.indexes
        if index.name == "uq_activity_goal_contributions_session_target_time"
    ]

    assert "ck_activity_goal_contributions_type" in checks
    assert "ck_activity_goal_contributions_value" in checks
    assert "unit = 'seconds'" in checks["ck_activity_goal_contributions_value"]
    assert "unit <> 'seconds'" in checks["ck_activity_goal_contributions_value"]
    assert len(time_indexes) == 1
    assert time_indexes[0].unique is True
    assert "time" in str(time_indexes[0].dialect_options["postgresql"]["where"])


def test_activity_child_records_enforce_session_ownership_and_preserve_values() -> None:
    session_unique_constraints = {
        tuple(column.name for column in constraint.columns)
        for constraint in ActivitySession.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert ("id", "user_id") in session_unique_constraints

    for model in (ActivityGoalContribution, ActivityCorrection):
        assert any(
            isinstance(constraint, ForeignKeyConstraint)
            and tuple(column.name for column in constraint.columns)
            == ("activity_session_id", "user_id")
            for constraint in model.__table__.constraints
        )

    assert isinstance(ActivityCorrection.__table__.c.previous_value.type, JSONB)
    assert isinstance(ActivityCorrection.__table__.c.new_value.type, JSONB)
    assert ActivityEvent.__table__.c.occurred_at.type.timezone is True


def test_correction_deletion_is_restricted_and_values_are_immutable() -> None:
    fk = next(
        constraint for constraint in ActivityCorrection.__table__.constraints
        if isinstance(constraint, ForeignKeyConstraint)
        and tuple(column.name for column in constraint.columns) == ("activity_session_id", "user_id")
    )
    assert fk.ondelete == "RESTRICT"
    row = ActivityCorrection(field_name="title", previous_value="a", new_value="b")
    try:
        row.field_name = "notes"
    except AttributeError:
        return
    assert False, "correction should be immutable"

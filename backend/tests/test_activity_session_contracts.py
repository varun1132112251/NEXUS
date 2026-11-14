from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.activity_event import ActivityEvent
from app.models.activity_session import ActivitySession
from app.models.activity_record import ActivityRecord
from app.models.activity_goal_contribution import ActivityGoalContribution
from app.models.activity_session_event import ActivitySessionEvent
from app.models.time_session import TimeSession
from app.models.time_session_segment import TimeSessionSegment
from app.schemas.activity_session import ActivitySessionCreate, ActivitySessionCorrectionRequest


def sample_interval():
    start = datetime(2026, 11, 1, 10, tzinfo=UTC)
    return start, start + timedelta(minutes=30)


def test_observed_session_requires_evidence_and_valid_interval():
    start, end = sample_interval()
    with pytest.raises(ValidationError):
        ActivitySessionCreate(title="Observed", started_at=start, ended_at=end, duration_seconds=1800, source_kind="observed")
    event_id = uuid4()
    created = ActivitySessionCreate(title="Observed", started_at=start, ended_at=end, duration_seconds=1800, source_kind="observed", event_ids=[event_id])
    assert created.event_ids == [event_id]


def test_manual_session_is_not_mislabeled_as_observed_evidence():
    start, end = sample_interval()
    with pytest.raises(ValidationError):
        ActivitySessionCreate(title="Manual", started_at=start, ended_at=end, duration_seconds=1800, source_kind="manual", event_ids=[uuid4()])
    with pytest.raises(ValidationError):
        ActivitySessionCreate(title="Manual", started_at=start, ended_at=end, duration_seconds=2000)


def test_activity_session_correction_requires_reason():
    with pytest.raises(ValidationError):
        ActivitySessionCorrectionRequest(title="Corrected")
    assert ActivitySessionCorrectionRequest(title="Corrected", reason="Wrong app title").title == "Corrected"


def test_models_expose_user_scoped_event_and_segment_edges():
    event_fks = [tuple(column.name for column in constraint.columns) for constraint in ActivitySessionEvent.__table__.foreign_key_constraints]
    assert ("activity_event_id", "user_id") in event_fks
    assert ("activity_session_id", "user_id") in event_fks
    assert any(tuple(column.name for column in constraint.columns) == ("id", "user_id") for constraint in ActivityEvent.__table__.constraints)
    assert "source_kind" in ActivitySession.__table__.columns
    assert "paused" in str(next(c for c in TimeSession.__table__.constraints if c.name == "ck_time_sessions_status").sqltext)
    assert any(index.name == "uq_time_session_segments_one_open" for index in TimeSessionSegment.__table__.indexes)
    contribution_fks = [tuple(column.name for column in constraint.columns) for constraint in ActivityGoalContribution.__table__.foreign_key_constraints]
    assert ("activity_session_id", "user_id") in contribution_fks
    assert ("activity_record_id", "user_id") in contribution_fks
    source_check = next(c for c in ActivityGoalContribution.__table__.constraints if c.name == "ck_activity_goal_contributions_source")
    assert "contribution_type <> 'time' OR activity_session_id IS NOT NULL" in str(source_check.sqltext)
    assert any(tuple(column.name for column in constraint.columns) == ("id", "user_id") for constraint in ActivityRecord.__table__.constraints)

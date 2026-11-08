from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import CheckConstraint

from app.models.personal_memory import PersonalMemory
from app.schemas.personal_memory import PersonalMemoryCreate, PersonalMemoryUpdate


def test_personal_memory_create_defaults_to_explicit_user_stated_provenance() -> None:
    payload = PersonalMemoryCreate(
        category="identity",
        title="Education",
        content="Studying B.Tech CSM.",
    )

    assert payload.importance == 3
    assert payload.details == {}
    assert payload.expires_at is None


def test_personal_memory_rejects_unknown_category() -> None:
    with pytest.raises(ValidationError):
        PersonalMemoryCreate(
            category="random",
            title="Unknown",
            content="This category must not be accepted.",
        )


def test_personal_memory_expiry_requires_timezone() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        PersonalMemoryCreate(
            category="commitment_context",
            title="Tomorrow plan",
            content="Study DBMS.",
            expires_at=datetime(2026, 11, 9, 20, 0),
        )


def test_personal_memory_update_supports_partial_changes() -> None:
    payload = PersonalMemoryUpdate(title="Updated title")

    assert payload.model_dump(exclude_unset=True) == {"title": "Updated title"}


def test_personal_memory_model_has_database_invariants() -> None:
    constraints = {
        constraint.name
        for constraint in PersonalMemory.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert "ck_personal_memories_category" in constraints
    assert "ck_personal_memories_source_kind" in constraints
    assert "ck_personal_memories_status" in constraints
    assert "ck_personal_memories_confidence" in constraints
    assert "ck_personal_memories_importance" in constraints

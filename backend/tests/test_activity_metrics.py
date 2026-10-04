import pytest
from fastapi import HTTPException

from app.api.v1.routes.activity_records import validate_details


def test_dsa_activity_accepts_consistent_evidence() -> None:
    validate_details(
        "problems_solved",
        {
            "problems_solved": 3,
            "attempted": 4,
            "mistakes": 1,
            "accuracy": 75,
        },
        3,
    )


def test_dsa_activity_rejects_solved_above_attempted() -> None:
    with pytest.raises(HTTPException, match="cannot exceed"):
        validate_details(
            "problems_solved",
            {"problems_solved": 5, "attempted": 3},
            5,
        )


def test_activity_rejects_invalid_accuracy() -> None:
    with pytest.raises(HTTPException, match="between 0 and 100"):
        validate_details("questions_solved", {"questions_solved": 2, "accuracy": 120}, 2)


def test_activity_rejects_metric_mismatch() -> None:
    with pytest.raises(HTTPException, match="must equal metric_value"):
        validate_details("pages_read", {"pages_read": 9}, 10)


def test_generic_execution_accepts_count_metric() -> None:
    validate_details("count", {"count": 1, "key_concepts": "Implemented API"}, 1)

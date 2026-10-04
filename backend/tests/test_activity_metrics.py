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


from datetime import date
from app.api.v1.routes.habits import best_calendar_streak, consecutive_streak, scheduled_streak


def test_consecutive_streak_counts_latest_chain() -> None:
    days = {date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 4)}
    assert consecutive_streak(days, date(2026, 10, 4)) == 1


def test_best_calendar_streak_finds_longest_chain() -> None:
    days = {date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3), date(2026, 10, 6)}
    assert best_calendar_streak(days) == 3


def test_scheduled_streak_uses_expected_occurrences() -> None:
    expected = {date(2026, 10, 1), date(2026, 10, 3), date(2026, 10, 5)}
    completed = {date(2026, 10, 1), date(2026, 10, 3), date(2026, 10, 5)}
    assert scheduled_streak(expected, completed, date(2026, 10, 5)) == 2

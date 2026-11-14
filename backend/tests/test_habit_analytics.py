from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from app.api.v1.routes.habits import expected_days
from app.models.habit import Habit
from app.services.planner import user_timezone


def test_habit_expected_days_distinguish_unscheduled_from_cancelled_schedule():
    habit = Habit(id=uuid4(), user_id=uuid4(), name="Daily practice", frequency="daily")
    start = date(2026, 6, 1)
    end = date(2026, 6, 3)

    assert expected_days(habit, start, end, set()) == {date(2026, 6, 1), date(2026, 6, 2), date(2026, 6, 3)}
    assert expected_days(habit, start, end, set(), has_schedule=True) == set()
    assert expected_days(habit, start, end, {date(2026, 6, 2)}, has_schedule=True) == {date(2026, 6, 2)}


@pytest.mark.parametrize("profile", [None, SimpleNamespace(timezone=""), SimpleNamespace(timezone="Not/A_Zone")])
def test_analytics_timezone_requires_a_valid_profile_timezone(profile):
    class ProfileLookup:
        def scalar(self, _query):
            return profile

    with pytest.raises(HTTPException) as error:
        user_timezone(ProfileLookup(), uuid4())
    assert error.value.status_code == 422

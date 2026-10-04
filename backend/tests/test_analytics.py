from app.api.v1.routes.analytics import build_insights


def test_analytics_insights_flag_low_schedule_completion() -> None:
    insights = build_insights(
        planned_seconds=3600,
        actual_seconds=1800,
        planned_items=10,
        completed_items=5,
        diary_days=2,
        range_days=7,
        breakdown=[],
    )
    assert any("Schedule completion is 50%" in item for item in insights)


def test_analytics_insights_flag_missing_reflections() -> None:
    insights = build_insights(
        planned_seconds=0,
        actual_seconds=1200,
        planned_items=0,
        completed_items=0,
        diary_days=0,
        range_days=7,
        breakdown=[],
    )
    assert insights == ["No execution evidence in this range yet."]


def test_analytics_insights_include_top_work_and_reflection_gap() -> None:
    insights = build_insights(
        planned_seconds=7200,
        actual_seconds=7200,
        planned_items=4,
        completed_items=4,
        diary_days=3,
        range_days=7,
        breakdown=[{
            "key": "dsa",
            "label": "DSA Practice",
            "seconds": 3600,
            "session_count": 3,
            "activity_count": 3,
            "metric_total": 8,
        }],
    )
    assert any("Reflection coverage is 3/7 days" in item for item in insights)
    assert any("Most focused time went to DSA Practice" in item for item in insights)

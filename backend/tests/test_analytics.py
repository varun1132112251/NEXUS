from datetime import date

from app.schemas.analytics import AnalyticsDay, AnalyticsSummary, AnalyticsTotals, ActivityBreakdown


def test_analytics_summary_accepts_activity_breakdown() -> None:
    payload = AnalyticsSummary(
        start_date=date(2026, 10, 4),
        end_date=date(2026, 10, 4),
        totals=AnalyticsTotals(
            planned_seconds=3600,
            actual_seconds=1800,
            planned_items=2,
            completed_items=1,
            skipped_items=0,
            schedule_completion_rate=50.0,
            session_count=1,
            activity_count=1,
            diary_days=1,
        ),
        daily=[
            AnalyticsDay(
                date=date(2026, 10, 4),
                planned_seconds=3600,
                actual_seconds=1800,
                planned_items=2,
                completed_items=1,
                activity_count=1,
            )
        ],
        target_progress=[],
        breakdown=[
            ActivityBreakdown(
                key="dsa",
                label="DSA Practice",
                seconds=1800,
                session_count=1,
                activity_count=1,
                metric_total=4,
            )
        ],
        reflection={
            "days_with_entries": 1,
            "days_with_accomplishments": 1,
            "days_with_learning": 0,
            "days_with_tomorrow_changes": 0,
            "days_with_distractions": 0,
            "coverage_percent": 100.0,
        },
        insights=[],
    )

    assert payload.breakdown[0].metric_total == 4
    assert payload.daily[0].actual_seconds == 1800
    assert payload.totals.time_execution_rate == 0.0


def test_analytics_totals_accept_time_execution_rate() -> None:
    totals = AnalyticsTotals(
        planned_seconds=3600,
        actual_seconds=1800,
        planned_items=2,
        completed_items=1,
        skipped_items=0,
        schedule_completion_rate=50.0,
        time_execution_rate=50.0,
        session_count=1,
        activity_count=1,
        diary_days=1,
    )
    assert totals.time_execution_rate == 50.0

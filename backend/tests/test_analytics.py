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
    )

    assert payload.breakdown[0].metric_total == 4
    assert payload.daily[0].actual_seconds == 1800

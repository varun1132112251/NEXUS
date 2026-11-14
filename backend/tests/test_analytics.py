from datetime import date

from app.schemas.analytics import (
    AnalyticsDay, AnalyticsSummary, AnalyticsTotals, ActivityBreakdown,
    DailyActualSummary, DailyDataQuality, DailyPlannedSummary, DailyReflection, DailyReport,
)


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


def test_daily_report_contract_accepts_empty_profile_local_day() -> None:
    payload = DailyReport(
        date=date(2026, 11, 14), timezone="Asia/Kolkata",
        planned=DailyPlannedSummary(
            planned_seconds=0, scheduled_blocks=0, completed_blocks=0, partial_blocks=0,
            skipped_blocks=0, missed_blocks=0, cancelled_blocks=0, planned_tasks=0,
            completed_tasks=0, in_progress_tasks=0, blocked_tasks=0, cancelled_tasks=0,
        ),
        actual=DailyActualSummary(
            confirmed_seconds=0, corrected_seconds=0, actual_seconds=0, draft_seconds=0,
            allocated_seconds=0, unallocated_seconds=0, outside_planned_seconds=0,
            ambiguous_seconds=0, overlapping_actual_seconds=0, ambiguous_allocation_seconds=0,
            confirmed_session_count=0, corrected_session_count=0, unavailable_legacy_seconds=0,
        ),
        activities=[], historical_activities=[], goal_contributions=[], goal_progress_history=[],
        tasks=[], schedule=[], task_history=[], schedule_history=[], activity_corrections=[],
        reflection=DailyReflection(available=False),
        data_quality=DailyDataQuality(
            draft_session_count=0, discarded_session_count=0, superseded_session_count=0,
            unlinked_observation_count=0, legacy_activity_record_count=0,
            unavailable_legacy_seconds=0, ambiguous_allocation_seconds=0,
        ),
    )
    assert payload.timezone == "Asia/Kolkata"
    assert payload.actual.actual_seconds == 0
    assert payload.reflection.available is False

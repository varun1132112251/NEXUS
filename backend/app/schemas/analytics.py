from datetime import date
from pydantic import BaseModel, Field
from app.schemas.schedule import ScheduleItemRead


class AnalyticsTotals(BaseModel):
    """Planned time excludes cancelled blocks; actual is unioned confirmed/corrected evidence.

    allocated_seconds contains ledger claims whose execution intervals can be attributed uniquely.
    Ambiguous claims are exposed separately; unallocated_seconds is unavailable when attribution
    cannot be reconstructed, and otherwise equals actual minus allocated time.
    unavailable_legacy_seconds reports credited stopwatch duration lacking segment evidence.
    """
    planned_seconds: int
    actual_seconds: int
    planned_items: int
    completed_items: int
    skipped_items: int
    partial_items: int = 0
    missed_items: int = 0
    cancelled_items: int = 0
    draft_seconds: int = 0
    allocated_seconds: int = 0
    unallocated_seconds: int | None = 0
    unavailable_legacy_seconds: int = 0
    allocation_overlap_excess_seconds: int = 0
    allocation_attribution_unavailable_seconds: int = 0
    schedule_completion_rate: float
    time_execution_rate: float = Field(default=0.0)
    session_count: int
    activity_count: int
    diary_days: int


class AnalyticsDay(BaseModel):
    date: date
    planned_seconds: int
    actual_seconds: int
    planned_items: int
    completed_items: int
    activity_count: int
    draft_seconds: int = 0


class ActivityBreakdown(BaseModel):
    """Exclusive category seconds; ambiguous_seconds overlap category intervals and are not assigned.

    key/source_kind preserve the ActivitySession source kind and normalized title. ActivityRecord
    counts and metric_total are legacy/manual measures and seconds remain zero.
    """
    key: str
    label: str
    seconds: int
    session_count: int
    activity_count: int
    metric_total: int
    source_kind: str = "activity_session"
    ambiguous_seconds: int = 0


class TargetProgress(BaseModel):
    id: str
    title: str
    month: date
    target_value: int | None
    current_value: int
    progress_percent: float | None
    status: str


class ReflectionSummary(BaseModel):
    days_with_entries: int
    days_with_accomplishments: int
    days_with_learning: int
    days_with_tomorrow_changes: int
    days_with_distractions: int
    coverage_percent: float


class AnalyticsSummary(BaseModel):
    start_date: date
    end_date: date
    totals: AnalyticsTotals
    daily: list[AnalyticsDay]
    target_progress: list[TargetProgress]
    breakdown: list[ActivityBreakdown]
    reflection: ReflectionSummary
    insights: list[str]


class ScheduleExecutionTotals(BaseModel):
    """Confirmed actual is unioned once; associated/outside/ambiguous partition its clock intervals.

    Legacy timer duration with no segment evidence is separately marked unavailable.
    """
    planned_seconds: int
    confirmed_actual_seconds: int
    associated_actual_seconds: int
    outside_planned_seconds: int
    ambiguous_actual_seconds: int
    unavailable_legacy_seconds: int
    planned_items: int
    completed_items: int
    partial_items: int
    missed_items: int
    skipped_items: int
    cancelled_items: int
    completion_rate: float


class ScheduleExecutionItem(BaseModel):
    schedule_item: ScheduleItemRead
    planned_seconds: int
    confirmed_actual_seconds: int
    outside_planned_seconds: int
    ambiguous_actual_seconds: int
    unavailable_legacy_seconds: int
    confirmed_session_count: int


class ScheduleExecutionSummary(BaseModel):
    items: list[ScheduleExecutionItem]
    totals: ScheduleExecutionTotals

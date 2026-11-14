from datetime import date, datetime
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
    confirmed_seconds: int = 0
    corrected_seconds: int = 0
    ambiguous_actual_seconds: int = 0
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
    confirmed_seconds: int = 0
    corrected_seconds: int = 0
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


class DailyPlannedSummary(BaseModel):
    planned_seconds: int
    scheduled_blocks: int
    completed_blocks: int
    partial_blocks: int
    skipped_blocks: int
    missed_blocks: int
    cancelled_blocks: int
    planned_tasks: int
    completed_tasks: int
    in_progress_tasks: int
    blocked_tasks: int
    cancelled_tasks: int


class DailyActualSummary(BaseModel):
    confirmed_seconds: int
    corrected_seconds: int
    actual_seconds: int
    draft_seconds: int
    allocated_seconds: int
    unallocated_seconds: int | None
    outside_planned_seconds: int
    ambiguous_seconds: int
    overlapping_actual_seconds: int
    ambiguous_allocation_seconds: int
    confirmed_session_count: int
    corrected_session_count: int
    unavailable_legacy_seconds: int


class DailyActivity(BaseModel):
    id: str
    title: str
    status: str
    source_kind: str
    started_at: datetime
    ended_at: datetime | None
    duration_seconds: int | None
    contribution_count: int
    evidence_event_count: int
    schedule_item_id: str | None = None
    task_id: str | None = None
    goal_id: str | None = None
    target_id: str | None = None


class DailyHistoricalActivity(BaseModel):
    id: str
    title: str
    activity_type: str
    metric_value: int | None
    recorded_at: datetime
    time_session_id: str | None


class DailyGoalContribution(BaseModel):
    id: str
    contribution_type: str
    value: str
    unit: str | None
    goal_id: str | None
    goal_title: str | None
    ambition_title: str | None
    target_id: str | None
    target_title: str | None
    activity_session_id: str | None
    activity_record_id: str | None
    reversed_at: datetime | None
    created_at: datetime


class DailyGoalProgress(BaseModel):
    id: str
    goal_id: str
    goal_title: str
    numeric_delta: str | None
    resulting_value: str | None
    qualitative_value: str | None
    unit: str | None
    source_kind: str
    corrects_entry_id: str | None
    reason: str | None
    created_at: datetime


class DailyActivityCorrection(BaseModel):
    id: str
    activity_session_id: str
    field_name: str
    previous_value: object
    new_value: object
    reason: str | None
    created_at: datetime


class DailyTask(BaseModel):
    id: str
    title: str
    status: str
    due_at: datetime | None
    priority: int


class DailyStatusChange(BaseModel):
    item_id: str
    previous_status: str | None
    new_status: str
    event_kind: str
    created_at: datetime


class DailyReflection(BaseModel):
    available: bool
    has_accomplishments: bool = False
    has_learning: bool = False
    has_distractions: bool = False
    has_tomorrow_changes: bool = False


class DailyDataQuality(BaseModel):
    draft_session_count: int
    discarded_session_count: int
    superseded_session_count: int
    unlinked_observation_count: int
    legacy_activity_record_count: int
    unavailable_legacy_seconds: int
    ambiguous_allocation_seconds: int


class DailyReport(BaseModel):
    date: date
    timezone: str
    planned: DailyPlannedSummary
    actual: DailyActualSummary
    activities: list[DailyActivity]
    historical_activities: list[DailyHistoricalActivity]
    goal_contributions: list[DailyGoalContribution]
    goal_progress_history: list[DailyGoalProgress]
    tasks: list[DailyTask]
    schedule: list[ScheduleItemRead]
    task_history: list[DailyStatusChange]
    schedule_history: list[DailyStatusChange]
    activity_corrections: list[DailyActivityCorrection]
    reflection: DailyReflection
    data_quality: DailyDataQuality


class PeriodComparisonMetric(BaseModel):
    current: int
    previous: int | None
    change: int | None
    percent_change: float | None


class HistoricalProgressItem(BaseModel):
    id: str
    goal_id: str | None = None
    goal_title: str | None = None
    ambition_title: str | None = None
    target_id: str | None = None
    target_title: str | None = None
    contribution_type: str | None = None
    value: str | None = None
    numeric_delta: str | None = None
    unit: str | None = None
    source_kind: str | None = None
    recorded_at: datetime
    created_at: datetime | None = None
    reversed_at: datetime | None = None
    qualitative_value: str | None = None
    resulting_value: str | None = None
    corrects_entry_id: str | None = None
    source_contribution_id: str | None = None
    reason: str | None = None


class HistoricalMilestone(BaseModel):
    id: str
    goal_id: str
    title: str
    status: str
    completed_at: date | None


class PeriodReport(BaseModel):
    period_type: str
    start_date: date
    end_date: date
    timezone: str
    totals: AnalyticsTotals
    daily: list[AnalyticsDay]
    days_with_confirmed_or_corrected_activity: int
    days_with_planned_activity: int
    days_with_no_recorded_activity: int
    outside_planned_seconds: int
    schedule_ambiguous_seconds: int
    task_status_transitions: dict[str, int]
    activity_distribution: list[ActivityBreakdown]
    contribution_count: int
    contributions: list[HistoricalProgressItem]
    progress_entries: list[HistoricalProgressItem]
    milestones: list[HistoricalMilestone]
    ambition_status_changes: list[dict]
    task_status_change_count: int
    schedule_status_change_count: int
    activity_correction_count: int
    reflection_days: int
    reflection_coverage_percent: float
    comparison: dict[str, PeriodComparisonMetric]
    history_limitations: list[str]


class GoalHistoryRead(BaseModel):
    goal_id: str
    ambition_id: str
    title: str
    status: str
    measurement_type: str
    measurement_unit: str | None
    current_value: str | None
    qualitative_value: str | None
    starting_value: str | None
    starting_value_status: str
    progress_entries: list[HistoricalProgressItem]
    contributions: list[HistoricalProgressItem]
    milestones: list[HistoricalMilestone]
    ambition_status_history: list[dict]
    goal_status_history_available: bool
    milestone_status_history_available: bool
    limitations: list[str]

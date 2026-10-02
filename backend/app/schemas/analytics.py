from datetime import date
from pydantic import BaseModel


class AnalyticsTotals(BaseModel):
    planned_seconds: int
    actual_seconds: int
    planned_items: int
    completed_items: int
    skipped_items: int
    schedule_completion_rate: float
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


class TargetProgress(BaseModel):
    id: str
    title: str
    month: date
    target_value: int | None
    current_value: int
    progress_percent: float | None
    status: str


class AnalyticsSummary(BaseModel):
    start_date: date
    end_date: date
    totals: AnalyticsTotals
    daily: list[AnalyticsDay]
    target_progress: list[TargetProgress]

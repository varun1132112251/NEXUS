# Batch 5.3 Historical Intelligence Architecture Audit

## Existing historical data sources

- `ActivitySession` plus `ActivitySessionEvent` and `ActivityCorrection` retain reviewed sessions, evidence links, and field corrections.
- `TimeSessionSegment` retains elapsed stopwatch intervals; paused time has no segment and is not counted.
- `ActivityGoalContribution` retains typed goal/target evidence, source references, and `reversed_at` corrections.
- `GoalProgressEntry` is append-only and stores signed measurements, resulting values, correction links, unit, source, and timestamp.
- `AmbitionLifecycleEvent`, `TaskStatusEvent`, and `ScheduleStatusEvent` are append-only status histories.
- `AmbitionMilestone.completed_at` records the current completion date, but milestone status changes are not historically appended.
- `DiaryEntry.entry_date` supports profile-local reflection coverage.
- `Target` stores current period progress, not an immutable historical series.
- Existing `/analytics/summary` computes bounded calendar-day totals and activity breakdown; `/analytics/daily-report` exposes detailed evidence for one profile-local date.

## Existing progress-history capabilities

Goal progress supports numeric and qualitative recorded values, correction entries, metric/time/milestone activity contributions, and reversals. Ambition lifecycle, task, and schedule status histories are available. Existing values are queried by their recorded timestamps and user ownership.

## Missing historical reporting capabilities

- No goal starting value or baseline timestamp is recorded. A goal's current value cannot be projected backward.
- Goal status changes are mutable and have no status event table.
- Milestone status is mutable; `completed_at` only describes its current state, not reopen/recomplete history.
- Target history is not append-only; current values do not establish past values.
- Daily analytics expose profile-local execution; weekly and monthly aggregate/comparison contracts do not exist.

This batch will not introduce snapshots or a migration. Reports will mark unrecorded baselines and missing goal/milestone status histories as unavailable. Adding append-only goal/milestone status events would require a separately reviewed migration.

## Proposed API contracts

- `GET /api/v1/analytics/weekly-report?week_start=YYYY-MM-DD`: Monday-based seven-day local calendar period; totals, daily series, consistency, activity distribution, progress/contribution/milestone/reflection history, and previous-week comparison.
- `GET /api/v1/analytics/monthly-report?month=YYYY-MM`: exact profile-local calendar month; same sections and previous-calendar-month comparison.
- `GET /api/v1/analytics/ambitions/goals/{goal_id}/history?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD`: current goal definition, recorded progress entries, typed contributions and reversals, current milestone state, recorded ambition lifecycle changes, and explicit reconstruction limitations.

All period ranges are bounded, profile timezone is authoritative, and percentages are omitted when the comparison baseline is zero or unavailable.

## Historical data limitations

Legacy `ActivityRecord` rows retain their recorded metric meaning and are not verified time. Stopwatch duration without retained segments is unavailable rather than synthesized. Starting values, past target values, goal status transitions, and milestone reopen history cannot be reconstructed from current rows.

## Required tests

- Empty periods, month lengths, month-boundary weeks, timezone and DST boundaries.
- Weekly/monthly totals versus constituent daily reports and adjacent periods.
- Verified/corrected/draft separation, paused timer exclusion, overlap and allocations.
- Goal metrics, progress corrections, reversed contributions, milestones and missing baselines.
- Task/schedule status history and reflection coverage.
- Ownership isolation and bounded period validation.
- Existing daily summary, planner and ambition API compatibility.

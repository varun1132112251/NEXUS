import React, { useEffect, useMemo, useState } from "react";
import { analyticsDateRange, profileDate, shiftAnalyticsDate } from "./plannerTimezone.js";

const API = `${(import.meta.env.VITE_API_URL || "http://127.0.0.1:8000").replace(/\/+$/, "")}/api/v1`;

const fmt = (seconds = 0) => {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m}m`;
};
const fmtProfileTime = (value, timeZone) => new Intl.DateTimeFormat(undefined, {
  timeZone, hour: "2-digit", minute: "2-digit",
}).format(new Date(value));

function AnalyticsView({ token, timeZone }) {
  const today = profileDate(new Date(), timeZone);
  const [preset, setPreset] = useState("week");
  const [endDate, setEndDate] = useState(today);
  const [data, setData] = useState(null);
  const [dailyReport, setDailyReport] = useState(null);
  const [dailyError, setDailyError] = useState("");
  const [habitStats, setHabitStats] = useState([]);
  const [habits, setHabits] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const range = useMemo(() => analyticsDateRange(endDate, preset), [preset, endDate]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        setError("");
        setDailyError("");
        setDailyReport(null);
        setLoading(true);
        const headers = { Authorization: `Bearer ${token}` };
        const [analyticsResponse, statsResponse, habitsResponse, dailyResponse] = await Promise.all([
          fetch(`${API}/analytics/summary?start_date=${range.start}&end_date=${range.end}`, { headers }),
          fetch(`${API}/habits/stats?start_date=${range.start}&end_date=${range.end}`, { headers }),
          fetch(`${API}/habits`, { headers }),
          fetch(`${API}/analytics/daily-report?date=${endDate}`, { headers }),
        ]);
        const body = await analyticsResponse.json().catch(() => null);
        const statsBody = await statsResponse.json().catch(() => null);
        const habitsBody = await habitsResponse.json().catch(() => null);
        const dailyBody = await dailyResponse.json().catch(() => null);
        if (!analyticsResponse.ok) throw new Error(body?.detail || `Request failed (${analyticsResponse.status})`);
        if (!statsResponse.ok) throw new Error(statsBody?.detail || `Habit stats request failed (${statsResponse.status})`);
        if (!habitsResponse.ok) throw new Error(habitsBody?.detail || `Habits request failed (${habitsResponse.status})`);
        if (!cancelled) {
          setData(body);
          setHabitStats(statsBody || []);
          setHabits(habitsBody || []);
          setDailyReport(dailyResponse.ok ? dailyBody : null);
          setDailyError(dailyResponse.ok ? "" : (dailyBody?.detail || `Daily report request failed (${dailyResponse.status})`));
        }
      } catch (err) {
        if (!cancelled) { setError(err.message); setData(null); }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [token, range.start, range.end, endDate]);

  const totals = data?.totals || {};
  const daily = data?.daily || [];
  const breakdown = data?.breakdown || [];
  const reflection = data?.reflection || {};
  const insights = data?.insights || [];

  return <section className="panel">
    <div className="panel-head">
      <div>
        <span className="eyebrow">ANALYTICS</span>
        <h3>Performance evidence</h3>
        <p className="muted small">{range.start} → {range.end}</p>
      </div>
      <div className="row-actions">
        <button aria-label="Previous analytics range" onClick={() => setEndDate(shiftAnalyticsDate(endDate, preset, -1))}>←</button>
        <input aria-label="Analytics date" type="date" value={endDate} onChange={event => setEndDate(event.target.value)} />
        <button aria-label="Next analytics range" onClick={() => setEndDate(shiftAnalyticsDate(endDate, preset, 1))}>→</button>
        {["day", "week", "month"].map(value =>
          <button key={value} className={preset === value ? "primary" : ""} onClick={() => setPreset(value)}>
            {value[0].toUpperCase() + value.slice(1)}
          </button>
        )}
      </div>
    </div>

    {error && <div className="error banner">{error}</div>}
    {loading ? <div className="loading">Loading analytics…</div> : !data ? <Empty text="Analytics are unavailable for this range." /> : <>
      <div className="metric-grid">
        <Metric label="Confirmed actual time" value={fmt(totals.actual_seconds)} />
        <Metric label="Planned time" value={fmt(totals.planned_seconds)} />
        <Metric label="Draft time (unconfirmed)" value={fmt(totals.draft_seconds)} />
        <Metric label="Allocated goal time" value={fmt(totals.allocated_seconds)} />
        <Metric label="Unallocated actual time" value={totals.unallocated_seconds === null ? "Unknown" : fmt(totals.unallocated_seconds)} />
        {totals.allocation_overlap_excess_seconds > 0 && <Metric label="Overlapping allocation claims" value={fmt(totals.allocation_overlap_excess_seconds)} />}
        {totals.allocation_attribution_unavailable_seconds > 0 && <Metric label="Allocation attribution unavailable" value={fmt(totals.allocation_attribution_unavailable_seconds)} />}
        {totals.unavailable_legacy_seconds > 0 && <Metric label="Legacy stopwatch time unavailable" value={fmt(totals.unavailable_legacy_seconds)} />}
        <Metric label="Schedule completion" value={`${totals.schedule_completion_rate || 0}%`} />
        <Metric label="Time execution" value={`${totals.time_execution_rate || 0}%`} />
        <Metric label="Sessions" value={totals.session_count || 0} />
        <Metric label="Manual activity records" value={totals.activity_count || 0} />
        <Metric label="Diary days" value={totals.diary_days || 0} />
      </div>
      {totals.unallocated_seconds === null && <p className="muted small">Some contribution time cannot be placed uniquely because its session crosses the selected date boundary or overlaps another confirmed interval.</p>}

      <div className="panel" style={{ marginTop: "1rem" }}>
        <PanelTitle eyebrow="DAILY REPORT" title={`Execution for ${endDate}`} />
        {dailyError ? <div className="error banner">{dailyError}</div> : !dailyReport ? <Empty text="Daily report is unavailable for this date." /> : <>
          <p className="muted small">Profile timezone: {dailyReport.timezone}. All times and date boundaries use this timezone.</p>
          <div className="metric-grid">
            <Metric label="Planned" value={fmt(dailyReport.planned.planned_seconds)} />
            <Metric label="Confirmed and corrected actual" value={fmt(dailyReport.actual.actual_seconds)} />
            <Metric label="Draft, unconfirmed" value={fmt(dailyReport.actual.draft_seconds)} />
            <Metric label="Allocated / unallocated" value={`${fmt(dailyReport.actual.allocated_seconds)} / ${dailyReport.actual.unallocated_seconds === null ? "Unknown" : fmt(dailyReport.actual.unallocated_seconds)}`} />
            <Metric label="Outside planned blocks" value={fmt(dailyReport.actual.outside_planned_seconds)} />
            <Metric label="Ambiguous overlapping time" value={fmt(dailyReport.actual.ambiguous_seconds)} />
            <Metric label="Scheduled blocks" value={`${dailyReport.planned.completed_blocks} completed · ${dailyReport.planned.partial_blocks} partial · ${dailyReport.planned.skipped_blocks} skipped · ${dailyReport.planned.missed_blocks} missed · ${dailyReport.planned.cancelled_blocks} cancelled`} />
            <Metric label="Tasks" value={`${dailyReport.planned.completed_tasks} completed · ${dailyReport.planned.in_progress_tasks} in progress · ${dailyReport.planned.blocked_tasks} blocked · ${dailyReport.planned.cancelled_tasks} cancelled`} />
          </div>
          <div className="two-col" style={{ marginTop: "1rem" }}>
            <div>
              <strong>Activity sessions</strong>
              {dailyReport.activities.length ? <div className="item-list">{dailyReport.activities.map(item => <div className="list-item" key={item.id}>
                <div><strong>{item.title}</strong><span>{item.status} · {item.source_kind} · {item.duration_seconds === null ? "Duration unavailable" : fmt(item.duration_seconds)} · {item.evidence_event_count} evidence event(s) · {item.contribution_count} contribution(s)</span></div>
              </div>)}</div> : <Empty text="No activity sessions recorded for this date." />}
              <strong>Goal contributions</strong>
              {dailyReport.goal_contributions.length ? <div className="item-list">{dailyReport.goal_contributions.map(item => <div className="list-item" key={item.id}>
                <div><strong>{item.goal_title || item.target_title || "Goal contribution"}</strong><span>{item.value} {item.unit || ""} · {item.contribution_type}{item.reversed_at ? " · reversed" : ""}</span></div>
              </div>)}</div> : <Empty text="No recorded goal contributions for this date." />}
              {dailyReport.goal_progress_history.map(entry => <div className="list-item" key={entry.id}><div><strong>{entry.goal_title}</strong><span>{entry.numeric_delta ?? entry.qualitative_value} {entry.unit || ""} · {entry.source_kind}{entry.corrects_entry_id ? " · correction" : ""}</span></div></div>)}
              {dailyReport.historical_activities.length > 0 && <>
                <strong>Historical activity records</strong>
                <div className="item-list">{dailyReport.historical_activities.map(item => <div className="list-item" key={item.id}><div><strong>{item.title}</strong><span>{item.activity_type}{item.metric_value === null ? "" : ` · ${item.metric_value}`} · not counted as verified time</span></div></div>)}</div>
              </>}
            </div>
            <div>
              <strong>Tasks and schedule</strong>
              {dailyReport.tasks.length ? <div className="item-list">{dailyReport.tasks.map(item => <div className="list-item" key={item.id}><div><strong>{item.title}</strong><span>{item.status}{item.due_at ? ` · due ${new Date(item.due_at).toLocaleTimeString([], { timeZone: dailyReport.timezone, hour: "2-digit", minute: "2-digit" })}` : ""}</span></div></div>)}</div> : <Empty text="No tasks due on this date." />}
              {dailyReport.schedule.length ? <div className="item-list">{dailyReport.schedule.map(item => <div className="list-item" key={item.id}><div><strong>{item.title}</strong><span>{item.status} · {fmtProfileTime(item.start_at, dailyReport.timezone)}–{fmtProfileTime(item.end_at, dailyReport.timezone)}</span></div></div>)}</div> : <Empty text="No scheduled blocks." />}
              <p className="muted small">Reflection: {dailyReport.reflection.available ? "entry available" : "no entry"}. Unlinked observations: {dailyReport.data_quality.unlinked_observation_count}; legacy activity records: {dailyReport.data_quality.legacy_activity_record_count}; unavailable legacy stopwatch time: {fmt(dailyReport.data_quality.unavailable_legacy_seconds)}.</p>
              <p className="muted small">Unconfirmed: {dailyReport.data_quality.draft_session_count}; discarded: {dailyReport.data_quality.discarded_session_count}; superseded: {dailyReport.data_quality.superseded_session_count}.</p>
              {dailyReport.data_quality.ambiguous_allocation_seconds > 0 && <p className="muted small">{fmt(dailyReport.data_quality.ambiguous_allocation_seconds)} allocated time has ambiguous session attribution.</p>}
              {dailyReport.task_history.length > 0 && <p className="muted small">Task status changes today: {dailyReport.task_history.map(change => `${change.item_id.slice(0, 8)} ${change.previous_status || "new"} → ${change.new_status}`).join(", ")}</p>}
              {dailyReport.schedule_history.length > 0 && <p className="muted small">Schedule lifecycle changes today: {dailyReport.schedule_history.map(change => `${change.item_id.slice(0, 8)} ${change.previous_status || "new"} → ${change.new_status}`).join(", ")}</p>}
              {dailyReport.activity_corrections.length > 0 && <p className="muted small">Activity corrections today: {dailyReport.activity_corrections.map(change => change.field_name).join(", ")}</p>}
            </div>
          </div>
        </>}
      </div>

      <div className="two-col" style={{ marginTop: "1rem" }}>
        <div className="panel">
          <PanelTitle eyebrow="HABITS" title="Consistency" />
          {habitStats.length ? <div className="item-list">
            {habitStats.map(stat => {
              const habit = habits.find(h => h.id === stat.habit_id);
              return <div className="list-item" key={stat.habit_id}>
                <div>
                  <strong>{habit?.name || "Habit"}</strong>
                  <span>{stat.completed_count}/{stat.expected_count} expected days with confirmed or corrected ActivitySessions · {stat.current_streak} current streak · {stat.best_streak} best</span>
                  <span>{fmt(stat.focused_seconds)} confirmed active time · {stat.manual_record_count} legacy/manual records (not counted as confirmed completion)</span>
                </div>
                <b>{stat.consistency_percent}%</b>
              </div>;
            })}
          </div> : <Empty text="No habits available in this range." />}
        </div>
        <div className="panel">
          <PanelTitle eyebrow="REFLECTION" title="Review quality" />
          <div className="metric-grid">
            <Metric label="Coverage" value={`${reflection.coverage_percent || 0}%`} />
            <Metric label="Entries" value={reflection.days_with_entries || 0} />
            <Metric label="Learning notes" value={reflection.days_with_learning || 0} />
            <Metric label="Tomorrow changes" value={reflection.days_with_tomorrow_changes || 0} />
          </div>
        </div>
      </div>

      <div className="panel" style={{ marginTop: "1rem" }}>
        <PanelTitle eyebrow="OBSERVATIONS" title="Recorded signals" />
        {insights.length ? <div className="item-list">
          {insights.map((insight, index) => <div className="list-item" key={index}><div><strong>Signal {index + 1}</strong><span>{insight}</span></div></div>)}
        </div> : <Empty text="No generated recommendations are included in these measurements." />}
      </div>

      <div className="two-col" style={{ marginTop: "1rem" }}>
        <div className="panel">
          <PanelTitle eyebrow="DAILY" title="Planned vs actual" />
          <div className="item-list">
            {daily.map(day => {
              const ratio = day.planned_seconds ? Math.min(100, day.actual_seconds / day.planned_seconds * 100) : 0;
              return <div className="list-item" key={day.date}>
                <div>
                  <strong>{day.date}</strong>
                  <span>{fmt(day.actual_seconds)} confirmed actual · {fmt(day.planned_seconds)} planned · {day.activity_count} manual records</span>
                </div>
                <b>{Math.round(ratio)}%</b>
              </div>;
            })}
          </div>
        </div>

        <div className="panel">
          <PanelTitle eyebrow="WORK" title="Where time went" />
        {breakdown.length ? <><p className="muted small">Category seconds show exclusive, unambiguous intervals. Overlapping category intervals are reported separately and are not assigned by priority.</p><div className="item-list">
            {breakdown.map(item => <div className="list-item" key={item.key}>
              <div>
                <strong>{item.label}</strong>
                <span>{item.session_count} sessions · {item.activity_count} activities</span>
              </div>
              <b>{fmt(item.seconds)}{item.ambiguous_seconds ? ` + ${fmt(item.ambiguous_seconds)} ambiguous` : ""}</b>
            </div>)}
          </div></> : <Empty text="No execution evidence in this range." />}
        </div>
      </div>

      <div className="panel" style={{ marginTop: "1rem" }}>
        <PanelTitle eyebrow="TARGETS" title="Current target progress" />
        {data.target_progress?.length ? data.target_progress.map(target =>
          <div key={target.id} className="target">
            <div className="target-line"><strong>{target.title}</strong><span>{target.current_value}/{target.target_value ?? "—"}</span></div>
            <div className="progress"><i style={{ width: `${Math.min(100, target.progress_percent || 0)}%` }} /></div>
            <small>{(target.progress_percent || 0).toFixed(0)}% complete</small>
          </div>
        ) : <Empty text="No targets in this range." />}
      </div>
    </>}
  </section>;
}

function PanelTitle({ eyebrow, title }) {
  return <div className="panel-head"><div><span className="eyebrow">{eyebrow}</span><h3>{title}</h3></div></div>;
}

function Metric({ label, value }) {
  return <div className="metric"><span>{label}</span><strong>{value}</strong></div>;
}

function Empty({ text }) {
  return <div className="empty">{text}</div>;
}

export default AnalyticsView;

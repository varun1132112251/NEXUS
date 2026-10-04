import React, { useEffect, useMemo, useState } from "react";

const API = "http://127.0.0.1:8000/api/v1";

const fmt = (seconds = 0) => {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m}m`;
};

const localDate = (d = new Date()) => {
  const x = new Date(d.getTime() - d.getTimezoneOffset() * 60000);
  return x.toISOString().slice(0, 10);
};

const shift = (value, days) => {
  const d = new Date(`${value}T12:00:00`);
  d.setDate(d.getDate() + days);
  return localDate(d);
};

function AnalyticsView({ token }) {
  const today = localDate();
  const [preset, setPreset] = useState("week");
  const [endDate, setEndDate] = useState(today);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  const range = useMemo(() => {
    if (preset === "day") return { start: endDate, end: endDate };
    const days = preset === "month" ? 29 : 6;
    return { start: shift(endDate, -days), end: endDate };
  }, [preset, endDate]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        setError("");
        const response = await fetch(`${API}/analytics/summary?start_date=${range.start}&end_date=${range.end}`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        const body = await response.json().catch(() => null);
        if (!response.ok) throw new Error(body?.detail || `Request failed (${response.status})`);
        if (!cancelled) setData(body);
      } catch (err) {
        if (!cancelled) setError(err.message);
      }
    })();
    return () => { cancelled = true; };
  }, [token, range.start, range.end]);

  const totals = data?.totals || {};
  const daily = data?.daily || [];
  const breakdown = data?.breakdown || [];

  return <section className="panel">
    <div className="panel-head">
      <div>
        <span className="eyebrow">ANALYTICS</span>
        <h3>Performance evidence</h3>
        <p className="muted small">{range.start} → {range.end}</p>
      </div>
      <div className="row-actions">
        {["day", "week", "month"].map(value =>
          <button key={value} className={preset === value ? "primary" : ""} onClick={() => setPreset(value)}>
            {value[0].toUpperCase() + value.slice(1)}
          </button>
        )}
      </div>
    </div>

    {error && <div className="error banner">{error}</div>}
    {!data ? <div className="loading">Loading analytics…</div> : <>
      <div className="metric-grid">
        <Metric label="Focused time" value={fmt(totals.actual_seconds)} />
        <Metric label="Planned time" value={fmt(totals.planned_seconds)} />
        <Metric label="Execution" value={`${totals.schedule_completion_rate || 0}%`} />
        <Metric label="Sessions" value={totals.session_count || 0} />
        <Metric label="Activities" value={totals.activity_count || 0} />
        <Metric label="Diary days" value={totals.diary_days || 0} />
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
                  <span>{fmt(day.actual_seconds)} actual · {fmt(day.planned_seconds)} planned</span>
                </div>
                <b>{Math.round(ratio)}%</b>
              </div>;
            })}
          </div>
        </div>

        <div className="panel">
          <PanelTitle eyebrow="WORK" title="Where time went" />
          {breakdown.length ? <div className="item-list">
            {breakdown.map(item => <div className="list-item" key={item.key}>
              <div>
                <strong>{item.label}</strong>
                <span>{item.session_count} sessions · {item.activity_count} activities</span>
              </div>
              <b>{fmt(item.seconds)}</b>
            </div>)}
          </div> : <Empty text="No execution evidence in this range." />}
        </div>
      </div>

      <div className="panel" style={{ marginTop: "1rem" }}>
        <PanelTitle eyebrow="TARGETS" title="Progress in selected range" />
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

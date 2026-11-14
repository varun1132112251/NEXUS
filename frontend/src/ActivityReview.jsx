import React, { useEffect, useState } from "react";

const API = `${(import.meta.env.VITE_API_URL || "http://127.0.0.1:8000").replace(/\/+$/, "")}/api/v1`;

async function request(path, token, options = {}) {
  const response = await fetch(API + path, {
    ...options,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}`, ...(options.headers || {}) },
  });
  if (response.status === 204) return null;
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new Error(body?.detail || `Request failed (${response.status})`);
  return body;
}

const isoLocal = value => new Date(value).toISOString();
const localInput = value => {
  const date = new Date(value);
  date.setMinutes(date.getMinutes() - date.getTimezoneOffset());
  return date.toISOString().slice(0, 16);
};

export default function ActivityReview({ token, targets }) {
  const [events, setEvents] = useState([]);
  const [sessions, setSessions] = useState([]);
  const [scheduleItems, setScheduleItems] = useState([]);
  const [selected, setSelected] = useState([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState({ title: "", started_at: "", ended_at: "", duration_seconds: "", schedule_item_id: "" });
  const [allocation, setAllocation] = useState({ session_id: "", destination: "", seconds: "" });
  const [metricAllocation, setMetricAllocation] = useState({ session_id: "", goal_id: "", value: "" });
  const [goalOptions, setGoalOptions] = useState([]);
  const [evidence, setEvidence] = useState({});
  const [corrections, setCorrections] = useState({});
  const [contributions, setContributions] = useState({});

  async function load() {
    try {
      setError("");
      const [eventRows, sessionRows, scheduleRows] = await Promise.all([
        request("/activity-events?status=all&limit=200", token),
        request("/activity-sessions?limit=200", token),
        request("/schedule?include_deleted=true", token),
      ]);
      setEvents(eventRows);
      setSessions(sessionRows);
      setScheduleItems(scheduleRows);
      const ambitionRows = await request("/ambitions", token);
      const goalRows = await Promise.all(ambitionRows.map(async ambition => (await request(`/ambitions/${ambition.id}/goals`, token)).map(goal => ({ ...goal, ambition_title: ambition.title }))));
      setGoalOptions(goalRows.flat().filter(goal => goal.status === "active"));
    } catch (err) { setError(err.message); }
  }
  useEffect(() => { load(); }, [token]);

  function toggleEvent(event) {
    setSelected(prev => {
      const next = prev.includes(event.id) ? prev.filter(id => id !== event.id) : [...prev, event.id];
      const chosen = events.filter(row => next.includes(row.id));
      if (chosen.length) {
        const first = [...chosen].sort((a, b) => new Date(a.occurred_at) - new Date(b.occurred_at))[0];
        const last = [...chosen].sort((a, b) => new Date(a.occurred_at) - new Date(b.occurred_at)).at(-1);
        const start = first.payload.started_at || first.occurred_at;
        const end = last.payload.transition === "ended" ? last.occurred_at : "";
        setDraft({ ...draft, title: first.payload.application || "Observed activity", started_at: localInput(start), ended_at: end ? localInput(end) : "", duration_seconds: end ? String(Math.max(0, Math.floor((new Date(end) - new Date(start)) / 1000))) : "" });
      }
      return next;
    });
  }

  async function createDraft(eventIds = []) {
    const started = new Date(draft.started_at);
    const ended = new Date(draft.ended_at);
    if (!draft.title.trim() || !draft.started_at || !draft.ended_at || ended <= started) {
      setError("Enter an activity, start time, and later end time.");
      return;
    }
    setBusy(true);
    try {
      await request("/activity-sessions", token, { method: "POST", body: JSON.stringify({
        title: draft.title.trim(), started_at: isoLocal(started), ended_at: isoLocal(ended),
        duration_seconds: Number(draft.duration_seconds || Math.floor((ended - started) / 1000)),
        source_kind: eventIds.length ? "observed" : "manual", event_ids: eventIds,
        schedule_item_id: draft.schedule_item_id || null,
      }) });
      setSelected([]);
      await load();
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  async function mutate(path, method = "POST", body) {
    setBusy(true);
    try { await request(path, token, { method, ...(body ? { body: JSON.stringify(body) } : {}) }); await load(); }
    catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  async function correct(session) {
    const title = window.prompt("Correct activity name", session.title);
    if (title === null || !title.trim()) return;
    const startedAt = window.prompt("Correct start timestamp (ISO with timezone)", new Date(session.started_at).toISOString());
    if (!startedAt) return;
    const endedAt = window.prompt("Correct end timestamp (ISO with timezone)", new Date(session.ended_at).toISOString());
    if (!endedAt) return;
    const duration = window.prompt("Correct credited duration in seconds", String(session.duration_seconds ?? 0));
    if (duration === null || !Number.isInteger(Number(duration)) || Number(duration) < 0) return;
    const reason = window.prompt("Why is this correction needed?");
    if (!reason?.trim()) return;
    await mutate(`/activity-sessions/${session.id}/correct`, "POST", { title: title.trim(), started_at: startedAt, ended_at: endedAt, duration_seconds: Number(duration), reason: reason.trim() });
  }

  async function inspectHistory(session) {
    try {
      const [sourceRows, correctionRows, contributionRows] = await Promise.all([
        request(`/activity-sessions/${session.id}/evidence`, token),
        request(`/activity-sessions/${session.id}/corrections`, token),
        request(`/activity-sessions/${session.id}/contributions`, token),
      ]);
      setEvidence(prev => ({ ...prev, [session.id]: sourceRows }));
      setCorrections(prev => ({ ...prev, [session.id]: correctionRows }));
      setContributions(prev => ({ ...prev, [session.id]: contributionRows }));
    } catch (err) { setError(err.message); }
  }

  async function allocateTime() {
    if (!allocation.session_id || !allocation.destination || Number(allocation.seconds) <= 0) return;
    const [kind, id] = allocation.destination.split(":");
    await mutate(`/activity-sessions/${allocation.session_id}/contributions`, "POST", { contributions: [{ [kind === "goal" ? "goal_id" : "target_id"]: id, contribution_type: "time", contribution_value: Number(allocation.seconds), unit: "seconds" }] });
    setAllocation({ session_id: "", destination: "", seconds: "" });
  }

  async function allocateMetric() {
    const goal = goalOptions.find(item => item.id === metricAllocation.goal_id);
    if (!metricAllocation.session_id || !goal || Number(metricAllocation.value) < 0) return;
    await mutate(`/activity-sessions/${metricAllocation.session_id}/contributions`, "POST", { contributions: [{ goal_id: goal.id, contribution_type: "metric", contribution_value: Number(metricAllocation.value), unit: goal.measurement_unit }] });
    setMetricAllocation({ session_id: "", goal_id: "", value: "" });
  }

  async function split(session) {
    const splitAt = window.prompt("Split at (ISO timestamp with timezone)", new Date(new Date(session.started_at).getTime() + Math.floor(session.duration_seconds / 2) * 1000).toISOString());
    if (!splitAt) return;
    const reason = window.prompt("Why split this session?");
    if (!reason?.trim()) return;
    await mutate(`/activity-sessions/${session.id}/split`, "POST", { split_at: splitAt, reason: reason.trim() });
  }

  async function merge(session) {
    const other = window.prompt("ID of a non-overlapping confirmed session to merge");
    if (!other) return;
    const reason = window.prompt("Why merge these sessions?");
    if (!reason?.trim()) return;
    await mutate(`/activity-sessions/${session.id}/merge`, "POST", { other_session_id: other, reason: reason.trim() });
  }

  const reviewable = sessions.filter(x => ["draft", "confirmed", "corrected"].includes(x.status));
  const activeScheduleItems = scheduleItems.filter(item => !item.deleted_at);
  return <section className="two-col">
    <div className="panel">
      <div className="panel-head"><div><span className="eyebrow">RAW OBSERVATIONS</span><h3>Review collected activity</h3></div><button className="ghost" onClick={load}>Refresh</button></div>
      <p className="muted small">These observations are evidence only. They are not classified as productive work.</p>
      {error && <div className="error banner">{error}</div>}
      {!events.length ? <div className="empty">No device observations found.</div> : <div className="item-list">{events.map(event => <label className="list-item" key={event.id} style={{ alignItems: "flex-start" }}>
        <input type="checkbox" disabled={Boolean(event.discarded_at) || event.session_ids.length > 0} checked={selected.includes(event.id)} onChange={() => toggleEvent(event)} />
        <div><strong>{event.payload.application || event.event_type} · {event.payload.transition || "observation"}</strong><span>{event.source_name} · PID {event.payload.process_id ?? "unknown"} · {new Date(event.occurred_at).toLocaleString()}</span><span>{event.session_ids.length ? `Linked sessions: ${event.session_ids.length}` : event.discarded_at ? "Discarded" : "Unreviewed"}</span></div>
        {!event.discarded_at && !event.session_ids.length && <button className="danger-text" type="button" onClick={() => mutate(`/activity-events/${event.id}/discard`)}>Discard observation</button>}
      </label>)}</div>}
      {selected.length > 0 && <div className="panel" style={{ marginTop: "1rem" }}><h3>Create observed draft</h3>
        <label>Activity<input value={draft.title} onChange={e => setDraft({ ...draft, title: e.target.value })} /></label>
        <label>Start<input type="datetime-local" value={draft.started_at} onChange={e => setDraft({ ...draft, started_at: e.target.value })} /></label>
        <label>End<input type="datetime-local" value={draft.ended_at} onChange={e => setDraft({ ...draft, ended_at: e.target.value })} /></label>
        <label>Planned block<select value={draft.schedule_item_id} onChange={e => setDraft({ ...draft, schedule_item_id: e.target.value })}><option value="">Unlinked activity</option>{activeScheduleItems.map(item=><option key={item.id} value={item.id}>{item.scheduled_date} · {item.title}</option>)}</select></label>
        <label>Credited seconds<input type="number" min="0" value={draft.duration_seconds} onChange={e => setDraft({ ...draft, duration_seconds: e.target.value })} /></label>
        <button className="primary" disabled={busy} onClick={() => createDraft(selected)}>Save draft with {selected.length} evidence event(s)</button>
      </div>}
    </div>
    <div className="panel">
      <div className="panel-head"><div><span className="eyebrow">ACTIVITY LEDGER</span><h3>Manual time and reviewed sessions</h3></div></div>
      <div className="panel">
        <h3>Manual time entry</h3>
        <label>Activity<input value={draft.title} onChange={e => setDraft({ ...draft, title: e.target.value })} placeholder="Reading, MMA, swimming…" /></label>
        <label>Start<input type="datetime-local" value={draft.started_at} onChange={e => setDraft({ ...draft, started_at: e.target.value })} /></label>
        <label>End<input type="datetime-local" value={draft.ended_at} onChange={e => setDraft({ ...draft, ended_at: e.target.value })} /></label>
        <label>Planned block<select value={draft.schedule_item_id} onChange={e => setDraft({ ...draft, schedule_item_id: e.target.value })}><option value="">Unlinked activity</option>{activeScheduleItems.map(item=><option key={item.id} value={item.id}>{item.scheduled_date} · {item.title}</option>)}</select></label>
        <label>Credited seconds<input type="number" min="0" value={draft.duration_seconds} onChange={e => setDraft({ ...draft, duration_seconds: e.target.value })} /></label>
        <button className="primary" disabled={busy} onClick={() => createDraft([])}>Save confirmed manual entry</button>
      </div>
      <div className="item-list">{reviewable.map(session => <div className="list-item" key={session.id}>
        <div><strong>{session.title}</strong><span>{session.source_kind} · {session.status} · {session.duration_seconds ?? "incomplete"} seconds</span><span>{new Date(session.started_at).toLocaleString()} – {session.ended_at ? new Date(session.ended_at).toLocaleString() : "open"}</span></div>
        <div className="row-actions">
          <select aria-label={`Planned block for ${session.title}`} value={session.schedule_item_id || ""} disabled={session.status === "discarded" || session.status === "superseded"} onChange={e=>mutate(`/activity-sessions/${session.id}/associations`, "PATCH", {schedule_item_id:e.target.value || null})}><option value="">Unlinked</option>{activeScheduleItems.map(item=><option key={item.id} value={item.id}>{item.scheduled_date} · {item.title}</option>)}</select>
          {session.status === "draft" && <button onClick={() => mutate(`/activity-sessions/${session.id}/confirm`)}>Confirm</button>}
          {session.status !== "discarded" && <button onClick={() => correct(session)}>Correct</button>}
          <button onClick={() => inspectHistory(session)}>Evidence / audit</button>
          {session.status !== "discarded" && <button className="danger-text" onClick={() => mutate(`/activity-sessions/${session.id}/discard`)}>Discard</button>}
          {["confirmed", "corrected"].includes(session.status) && <><button onClick={() => split(session)}>Split</button><button onClick={() => merge(session)}>Merge</button></>}
        </div>
      </div>)}</div>
      <div className="item-list">{reviewable.filter(x => evidence[x.id] || corrections[x.id] || contributions[x.id]).map(session => <details className="list-item" key={`history-${session.id}`} open>
        <summary>{session.title} evidence and correction history</summary>
        {(evidence[session.id] || []).map(row => <span key={row.id}>{row.source_name} · {row.event_type} · {row.payload.application || "event"} · {row.payload.transition || "observation"} · {new Date(row.occurred_at).toLocaleString()}</span>)}
        {(contributions[session.id] || []).map(row => <span key={row.id}>{row.target_title} · {row.contribution_type}: {row.contribution_value} {row.unit || ""}{row.reversed_at ? ` · reversed ${new Date(row.reversed_at).toLocaleString()}` : <button type="button" className="danger-text" onClick={async () => { const reason = window.prompt("Why reverse this contribution?"); if (reason?.trim()) { await mutate(`/activity-sessions/${session.id}/contributions/${row.id}?reason=${encodeURIComponent(reason.trim())}`, "DELETE"); await inspectHistory(session); } }}>Reverse with audit</button>}</span>)}
        {(corrections[session.id] || []).map(row => <span key={row.id}>{row.field_name}: {JSON.stringify(row.previous_value)} → {JSON.stringify(row.new_value)} · {row.reason || "No reason"} · {new Date(row.created_at).toLocaleString()}</span>)}
      </details>)}</div>
      <div className="form-grid">
        <label>Session<select value={allocation.session_id} onChange={e => setAllocation({ ...allocation, session_id: e.target.value })}><option value="">Choose confirmed session</option>{reviewable.filter(x => ["confirmed", "corrected"].includes(x.status)).map(x => <option key={x.id} value={x.id}>{x.title} · {x.duration_seconds}s</option>)}</select></label>
        <label>Time goal or target<select value={allocation.destination} onChange={e => setAllocation({ ...allocation, destination: e.target.value })}><option value="">Choose destination</option>{targets.filter(x => ["time", "seconds", "duration"].includes(x.metric_type)).map(x => <option key={x.id} value={`target:${x.id}`}>Target · {x.title}</option>)}{goalOptions.filter(x => x.measurement_type === "duration" && x.measurement_unit === "seconds").map(x => <option key={x.id} value={`goal:${x.id}`}>{x.ambition_title} · {x.title}</option>)}</select></label>
        <label>Seconds<input type="number" min="1" value={allocation.seconds} onChange={e => setAllocation({ ...allocation, seconds: e.target.value })} /></label>
        <button className="primary" disabled={busy} onClick={allocateTime}>Allocate time</button>
      </div>
      <div className="form-grid">
        <label>Confirmed activity<select value={metricAllocation.session_id} onChange={e => setMetricAllocation({ ...metricAllocation, session_id: e.target.value })}><option value="">Choose session</option>{reviewable.filter(x => ["confirmed", "corrected"].includes(x.status)).map(x => <option key={x.id} value={x.id}>{x.title}</option>)}</select></label>
        <label>Numeric ambition goal<select value={metricAllocation.goal_id} onChange={e => setMetricAllocation({ ...metricAllocation, goal_id: e.target.value })}><option value="">Choose goal</option>{goalOptions.filter(x => !["duration", "qualitative"].includes(x.measurement_type)).map(x => <option key={x.id} value={x.id}>{x.ambition_title} · {x.title} ({x.measurement_unit || x.measurement_type})</option>)}</select></label>
        <label>Measured value<input type="number" min="0" step="any" value={metricAllocation.value} onChange={e => setMetricAllocation({ ...metricAllocation, value: e.target.value })} /></label>
        <button className="primary" disabled={busy} onClick={allocateMetric}>Attribute metric</button>
      </div>
    </div>
  </section>;
}

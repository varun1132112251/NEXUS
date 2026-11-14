import React, { useEffect, useState } from "react";

const API = `${(import.meta.env.VITE_API_URL || "http://127.0.0.1:8000").replace(/\/+$/, "")}/api/v1`;
const MEASURES = ["count", "duration", "distance", "weight", "currency", "percentage", "proficiency", "custom", "qualitative"];

async function request(path, token, options = {}) {
  const response = await fetch(API + path, { ...options, headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}`, ...(options.headers || {}) } });
  if (response.status === 204) return null;
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new Error(body?.detail || `Request failed (${response.status})`);
  return body;
}

export default function Ambitions({ token }) {
  const [ambitions, setAmbitions] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [goals, setGoals] = useState({});
  const [milestones, setMilestones] = useState({});
  const [history, setHistory] = useState({});
  const [lifecycleHistory, setLifecycleHistory] = useState({});
  const [targets, setTargets] = useState([]);
  const [projects, setProjects] = useState([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ title: "", description: "", category: "personal", priority: 3, start_date: new Date().toISOString().slice(0, 10), target_date: "" });
  const [goalForm, setGoalForm] = useState({ ambition_id: "", title: "", description: "", measurement_type: "count", measurement_unit: "count", measurement_definition: "", target_value: "", start_date: new Date().toISOString().slice(0, 10), target_date: "", supporting_project_id: "" });
  const [progressForm, setProgressForm] = useState({});
  const [milestoneForm, setMilestoneForm] = useState({});
  const [targetForm, setTargetForm] = useState({});

  async function load() {
    try {
      setError("");
      const [rows, templateRows, targetRows, projectRows] = await Promise.all([
        request("/ambitions?include_archived=true", token),
        request("/ambitions/templates", token),
        request("/targets", token),
        request("/projects", token),
      ]);
      setAmbitions(rows); setTemplates(templateRows); setTargets(targetRows); setProjects(projectRows);
      const goalPairs = await Promise.all(rows.map(async ambition => [ambition.id, await request(`/ambitions/${ambition.id}/goals`, token)]));
      const lifecyclePairs = await Promise.all(rows.map(async ambition => [ambition.id, await request(`/ambitions/${ambition.id}/history`, token)]));
      setLifecycleHistory(Object.fromEntries(lifecyclePairs));
      const nextGoals = Object.fromEntries(goalPairs);
      setGoals(nextGoals);
      const allGoals = Object.values(nextGoals).flat();
      const related = await Promise.all(allGoals.map(async goal => {
        const [milestoneRows, progressRows] = await Promise.all([
          request(`/ambitions/goals/${goal.id}/milestones`, token),
          request(`/ambitions/goals/${goal.id}/progress`, token),
        ]);
        return [goal.id, milestoneRows, progressRows];
      }));
      setMilestones(Object.fromEntries(related.map(([id, value]) => [id, value])));
      setHistory(Object.fromEntries(related.map(([id, , value]) => [id, value])));
    } catch (err) { setError(err.message); }
  }
  useEffect(() => { load(); }, [token]);

  async function mutate(fn) {
    setBusy(true); setError("");
    try { await fn(); await load(); }
    catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  function chooseTemplate(template) {
    setForm({ ...form, title: template.title, description: template.description, category: template.category });
  }
  async function createAmbition(event) {
    event.preventDefault();
    await mutate(async () => { await request("/ambitions", token, { method: "POST", body: JSON.stringify({ ...form, target_date: form.target_date || null, priority: Number(form.priority) }) }); setForm({ ...form, title: "", description: "" }); });
  }
  async function createGoal(event) {
    event.preventDefault();
    await mutate(async () => {
      const payload = { ...goalForm, start_date: goalForm.start_date, target_date: goalForm.target_date || null, supporting_project_id: goalForm.supporting_project_id || null, target_value: goalForm.target_value === "" ? null : Number(goalForm.target_value) };
      await request(`/ambitions/${goalForm.ambition_id}/goals`, token, { method: "POST", body: JSON.stringify(payload) });
      setGoalForm({ ...goalForm, title: "", description: "", target_value: "" });
    });
  }
  async function recordProgress(goal) {
    const value = progressForm[goal.id] || {};
    const payload = goal.measurement_type === "qualitative"
      ? { qualitative_value: value.qualitative_value || "", reason: value.reason || null }
      : { numeric_delta: Number(value.numeric_delta), unit: goal.measurement_unit, reason: value.reason || null };
    await mutate(() => request(`/ambitions/goals/${goal.id}/progress`, token, { method: "POST", body: JSON.stringify(payload) }));
    setProgressForm(prev => ({ ...prev, [goal.id]: {} }));
  }
  async function correctProgress(goal, entry) {
    const delta = window.prompt(`Correction amount in ${goal.measurement_unit || "the goal's unit"} (negative reverses progress)`, entry.numeric_delta === null ? "" : String(-Number(entry.numeric_delta)));
    if (delta === null) return;
    const reason = window.prompt("Why is this correction needed?");
    if (!reason?.trim()) return;
    await mutate(() => request(`/ambitions/goals/${goal.id}/progress/${entry.id}/correct`, token, { method: "POST", body: JSON.stringify({ numeric_delta: Number(delta), unit: goal.measurement_unit, reason: reason.trim() }) }));
  }
  async function createMilestone(goal) {
    const value = milestoneForm[goal.id] || {};
    if (!value.title?.trim()) return;
    await mutate(async () => {
      await request(`/ambitions/goals/${goal.id}/milestones`, token, { method: "POST", body: JSON.stringify({ title: value.title.trim(), due_date: value.due_date || null }) });
      setMilestoneForm(prev => ({ ...prev, [goal.id]: {} }));
    });
  }
  async function createTarget(goal) {
    const value = targetForm[goal.id] || {};
    if (!value.title?.trim() || !value.month) return;
    await mutate(() => request("/targets", token, { method: "POST", body: JSON.stringify({ title: value.title.trim(), description: null, period_start: value.month, metric_type: value.metric_type || "count", target_value: Number(value.target_value || 0), period_type: value.period_type || "monthly", ambition_goal_id: goal.id }) }));
  }
  async function lifecycle(ambition, status) {
    const reason = window.prompt(`Optional reason for setting ${status}`, "");
    if (reason === null) return;
    await mutate(() => request(`/ambitions/${ambition.id}/lifecycle`, token, { method: "POST", body: JSON.stringify({ status, reason: reason || null }) }));
  }
  async function editAmbition(ambition) {
    const title = window.prompt("Ambition title", ambition.title);
    if (title === null || !title.trim()) return;
    const description = window.prompt("Description", ambition.description || "");
    if (description === null) return;
    const category = window.prompt("Category", ambition.category);
    if (!category?.trim()) return;
    await mutate(() => request(`/ambitions/${ambition.id}`, token, { method: "PATCH", body: JSON.stringify({ title: title.trim(), description: description || null, category: category.trim() }) }));
  }
  async function reorder(ambition, direction) {
    const active = ambitions.filter(item => item.status !== "archived");
    const index = active.findIndex(item => item.id === ambition.id);
    const next = index + direction;
    if (index < 0 || next < 0 || next >= active.length) return;
    [active[index], active[next]] = [active[next], active[index]];
    await mutate(() => request(`/ambitions/reorder?${active.map(item => `ambition_ids=${item.id}`).join("&")}`, token, { method: "PUT" }));
  }

  return <section className="two-col">
    <div className="panel">
      <div className="panel-head"><div><span className="eyebrow">LONG HORIZON</span><h3>Your ambitions</h3></div><button className="ghost" onClick={load}>Refresh</button></div>
      <p className="muted small">Choose your own direction, measures, and pace. Templates are optional starting points.</p>
      {error && <div className="error banner">{error}</div>}
      {ambitions.map((ambition, index) => <details className="list-item" key={ambition.id} open>
        <summary><strong>{ambition.title}</strong> · {ambition.category} · {ambition.status} · Priority {ambition.priority}{ambition.target_date ? ` · due ${ambition.target_date}` : ""}</summary>
        <span>{ambition.description || "No description"}</span>
        <div className="row-actions">
          {ambition.status !== "archived" && <button onClick={() => lifecycle(ambition, ambition.status === "paused" ? "active" : "paused")}>{ambition.status === "paused" ? "Resume" : "Pause"}</button>}
          {ambition.status !== "archived" && <button onClick={() => editAmbition(ambition)}>Edit</button>}
          {ambition.status !== "completed" && ambition.status !== "archived" && <button onClick={() => lifecycle(ambition, "completed")}>Complete</button>}
          {ambition.status !== "archived" && <button className="danger-text" onClick={() => lifecycle(ambition, "archived")}>Archive</button>}
          {ambition.status === "archived" && <button onClick={() => lifecycle(ambition, "active")}>Restore</button>}
          {ambition.status !== "archived" && <><button disabled={index === 0} onClick={() => reorder(ambition, -1)}>Move up</button><button disabled={index === ambitions.filter(x => x.status !== "archived").length - 1} onClick={() => reorder(ambition, 1)}>Move down</button></>}
        </div>
        <details><summary>Lifecycle history ({(lifecycleHistory[ambition.id] || []).length})</summary>{(lifecycleHistory[ambition.id] || []).map(row => <span key={row.id}>{row.previous_status} → {row.new_status}{row.reason ? ` · ${row.reason}` : ""} · {new Date(row.created_at).toLocaleString()}</span>)}</details>
        {(goals[ambition.id] || []).map(goal => <div className="panel" key={goal.id}>
          <div className="panel-head"><div><span className="eyebrow">{goal.measurement_type}{goal.measurement_unit ? ` · ${goal.measurement_unit}` : ""}</span><h3>{goal.title}</h3></div><span>{goal.status} · Priority {goal.priority}</span></div>
          <p>{goal.description || goal.measurement_definition || ""}</p>
          <p className="muted small">Progress: {goal.measurement_type === "qualitative" ? goal.qualitative_value || "No measurement recorded" : `${goal.current_value} ${goal.measurement_unit || ""}${goal.target_value !== null ? ` / ${goal.target_value}` : ""}`}{goal.target_date ? ` · target ${goal.target_date}` : ""}</p>
          <div className="form-grid">
            {goal.measurement_type === "qualitative" ? <label>Record current state<input value={progressForm[goal.id]?.qualitative_value || ""} onChange={e => setProgressForm(prev => ({ ...prev, [goal.id]: { ...prev[goal.id], qualitative_value: e.target.value } }))} /></label> : <label>Progress adjustment<input type="number" step="any" value={progressForm[goal.id]?.numeric_delta || ""} onChange={e => setProgressForm(prev => ({ ...prev, [goal.id]: { ...prev[goal.id], numeric_delta: e.target.value } }))} placeholder={`Increment or decrement (${goal.measurement_unit})`} /></label>}
            <label>Reason (required for decrement)<input value={progressForm[goal.id]?.reason || ""} onChange={e => setProgressForm(prev => ({ ...prev, [goal.id]: { ...prev[goal.id], reason: e.target.value } }))} /></label>
            <button disabled={busy} onClick={() => recordProgress(goal)}>Record progress</button>
          </div>
          <details><summary>Milestones</summary>
            {(milestones[goal.id] || []).map(item => <div className="list-item" key={item.id}><span>{item.title} · {item.status}{item.due_date ? ` · due ${item.due_date}` : ""}</span><button onClick={() => mutate(() => request(`/ambitions/milestones/${item.id}`, token, { method: "PATCH", body: JSON.stringify({ status: item.status === "completed" ? "open" : "completed" }) }))}>{item.status === "completed" ? "Reopen" : "Complete"}</button></div>)}
            <div className="inline-fields"><input placeholder="Milestone title" value={milestoneForm[goal.id]?.title || ""} onChange={e => setMilestoneForm(prev => ({ ...prev, [goal.id]: { ...prev[goal.id], title: e.target.value } }))} /><input type="date" value={milestoneForm[goal.id]?.due_date || ""} onChange={e => setMilestoneForm(prev => ({ ...prev, [goal.id]: { ...prev[goal.id], due_date: e.target.value } }))} /><button onClick={() => createMilestone(goal)}>Add milestone</button></div>
          </details>
          <details><summary>Progress history and activity sources ({(history[goal.id] || []).length})</summary>
            {(history[goal.id] || []).map(entry => <div className="list-item" key={entry.id}><span>{entry.source_kind} · {entry.numeric_delta !== null ? `${entry.numeric_delta} ${entry.unit || ""} → ${entry.resulting_value}` : entry.qualitative_value}{entry.reason ? ` · ${entry.reason}` : ""}{entry.source_contribution_id ? ` · contribution ${entry.source_contribution_id}` : ""} · {new Date(entry.created_at).toLocaleString()}</span>{entry.source_kind !== "correction" && entry.numeric_delta !== null && <button onClick={() => correctProgress(goal, entry)}>Correct</button>}</div>)}
          </details>
          <details><summary>Linked period targets ({targets.filter(target => target.ambition_goal_id === goal.id).length})</summary>
            {targets.filter(target => target.ambition_goal_id === goal.id).map(target => <div className="list-item" key={target.id}><span>{target.period_type} · {target.title} · {target.current_value}/{target.target_value}</span></div>)}
            <div className="form-grid"><label>Target name<input value={targetForm[goal.id]?.title || ""} onChange={e => setTargetForm(prev => ({ ...prev, [goal.id]: { ...prev[goal.id], title: e.target.value } }))} /></label><label>Period<select value={targetForm[goal.id]?.period_type || "monthly"} onChange={e => setTargetForm(prev => ({ ...prev, [goal.id]: { ...prev[goal.id], period_type: e.target.value } }))}><option value="monthly">Monthly</option><option value="weekly">Weekly</option></select></label><label>Period start<input type="date" value={targetForm[goal.id]?.month || ""} onChange={e => setTargetForm(prev => ({ ...prev, [goal.id]: { ...prev[goal.id], month: e.target.value } }))} /></label><label>Metric<select value={targetForm[goal.id]?.metric_type || "count"} onChange={e => setTargetForm(prev => ({ ...prev, [goal.id]: { ...prev[goal.id], metric_type: e.target.value } }))}><option value="count">Count</option><option value="problems_solved">Problems solved</option><option value="pages_read">Pages read</option><option value="sessions_completed">Sessions completed</option><option value="books_completed">Books completed</option></select></label><label>Target value<input type="number" min="0" value={targetForm[goal.id]?.target_value || ""} onChange={e => setTargetForm(prev => ({ ...prev, [goal.id]: { ...prev[goal.id], target_value: e.target.value } }))} /></label><button onClick={() => createTarget(goal)}>Add period target</button></div>
          </details>
        </div>)}
      </details>)}
    </div>
    <div className="panel">
      <div className="panel"><span className="eyebrow">DEFINE YOUR OWN</span><h3>Create an ambition</h3>
        <div className="inline-fields"><select defaultValue="" onChange={e => { const item = templates.find(row => row.title === e.target.value); if (item) chooseTemplate(item); }}><option value="">Optional starting template</option>{templates.map(item => <option key={item.title} value={item.title}>{item.title}</option>)}</select></div>
        <form className="form-grid" onSubmit={createAmbition}><label>Title<input value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} required /></label><label>Description<textarea value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} /></label><label>Category<input value={form.category} onChange={e => setForm({ ...form, category: e.target.value })} required /></label><label>Priority<select value={form.priority} onChange={e => setForm({ ...form, priority: e.target.value })}>{[1,2,3,4,5].map(value => <option key={value}>{value}</option>)}</select></label><label>Start date<input type="date" value={form.start_date} onChange={e => setForm({ ...form, start_date: e.target.value })} required /></label><label>Optional target date<input type="date" value={form.target_date} onChange={e => setForm({ ...form, target_date: e.target.value })} /></label><button className="primary">Create ambition</button></form>
      </div>
      <div className="panel"><span className="eyebrow">MEASURABLE OUTCOMES</span><h3>Add a goal</h3>
        <form className="form-grid" onSubmit={createGoal}><label>Parent ambition<select value={goalForm.ambition_id} onChange={e => setGoalForm({ ...goalForm, ambition_id: e.target.value })} required><option value="">Choose ambition</option>{ambitions.filter(item => item.status !== "archived" && item.status !== "completed").map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label><label>Goal title<input value={goalForm.title} onChange={e => setGoalForm({ ...goalForm, title: e.target.value })} required /></label><label>Description<textarea value={goalForm.description} onChange={e => setGoalForm({ ...goalForm, description: e.target.value })} /></label><label>Supporting project<select value={goalForm.supporting_project_id} onChange={e => setGoalForm({ ...goalForm, supporting_project_id: e.target.value })}><option value="">None</option>{projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label><label>Measurement type<select value={goalForm.measurement_type} onChange={e => setGoalForm({ ...goalForm, measurement_type: e.target.value, measurement_unit: e.target.value === "duration" ? "seconds" : e.target.value === "count" ? "count" : "" })}>{MEASURES.map(value => <option key={value}>{value}</option>)}</select></label>{goalForm.measurement_type !== "qualitative" && <label>Unit<input value={goalForm.measurement_unit} onChange={e => setGoalForm({ ...goalForm, measurement_unit: e.target.value })} placeholder="e.g. km, kg, USD, problems" /></label>}<label>How will you measure it?<textarea value={goalForm.measurement_definition} onChange={e => setGoalForm({ ...goalForm, measurement_definition: e.target.value })} /></label><label>Optional target value<input type="number" step="any" min="0" value={goalForm.target_value} onChange={e => setGoalForm({ ...goalForm, target_value: e.target.value })} /></label><label>Start date<input type="date" value={goalForm.start_date} onChange={e => setGoalForm({ ...goalForm, start_date: e.target.value })} required /></label><label>Optional target date<input type="date" value={goalForm.target_date} onChange={e => setGoalForm({ ...goalForm, target_date: e.target.value })} /></label><button className="primary" disabled={busy}>Create goal</button></form>
      </div>
    </div>
  </section>;
}

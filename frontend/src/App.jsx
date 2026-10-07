import AnalyticsView from "./AnalyticsView";
import ProfileOnboarding from "./ProfileOnboarding";
import React, { useEffect, useMemo, useState } from "react";

const API = "http://127.0.0.1:8000/api/v1";

function api(path, options = {}, token) {
  return fetch(API + path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    },
  }).then(async (r) => {
    const data = await r.json().catch(() => null);
    if (!r.ok) throw new Error(data?.detail || `Request failed (${r.status})`);
    return data;
  });
}

const localDate = (d = new Date()) => {
  const x = new Date(d.getTime() - d.getTimezoneOffset() * 60000);
  return x.toISOString().slice(0, 10);
};
const localDateTime = (d = new Date()) => {
  const x = new Date(d.getTime() - d.getTimezoneOffset() * 60000);
  return x.toISOString().slice(0, 16);
};
const formatSeconds = (s = 0) => {
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return h ? `${h}h ${m}m` : m ? `${m}m` : `${sec}s`;
};
const formatClock = (iso) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
const isoFromLocal = (value) => {
  const d = new Date(value);
  const offset = -d.getTimezoneOffset();
  const sign = offset >= 0 ? "+" : "-";
  const hh = String(Math.floor(Math.abs(offset) / 60)).padStart(2, "0");
  const mm = String(Math.abs(offset) % 60).padStart(2, "0");
  return `${value}:00${sign}${hh}:${mm}`;
};


const inferMetricType = (title = "") => {
  const t = title.toLowerCase();
  if (t.includes("dsa") || t.includes("problem")) return "problems_solved";
  if (t.includes("book") && (t.includes("read") || t.includes("reading"))) return "books_completed";
  if (t.includes("english") && t.includes("session")) return "sessions_completed";
  if (t.includes("gate") && t.includes("revision")) return "topics_revised";
  if (t.includes("gate") && t.includes("question")) return "questions_solved";
  if (t.includes("nexus") && (t.includes("complete") || t.includes("v1"))) return "milestones_completed";
  return "count";
};

const METRIC_OPTIONS = [
  ["problems_solved", "DSA problems solved"],
  ["pages_read", "Reading pages"],
  ["sessions_completed", "Practice sessions"],
  ["questions_solved", "Questions solved"],
  ["topics_revised", "Topics revised"],
  ["milestones_completed", "Project milestones"],
  ["books_completed", "Books completed"],
  ["count", "Generic count"],
];
const METRIC_LABELS = Object.fromEntries(METRIC_OPTIONS);
const metricKey = (type) => ({
  problems_solved: "problems_solved",
  pages_read: "pages_read",
  sessions_completed: "sessions_completed",
  questions_solved: "questions_solved",
  topics_revised: "topics_revised",
  milestones_completed: "milestones_completed",
  books_completed: "books_completed",
  count: "count",
}[type] || "count");

function Login({ onLogin }) {
  const [mode, setMode] = useState("login");
  const [identifier, setIdentifier] = useState("");
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (mode === "register") {
        await api("/users", {
          method: "POST",
          body: JSON.stringify({ username: username.trim(), email: email.trim(), password }),
        });
        const data = await api("/auth/login", {
          method: "POST",
          body: JSON.stringify({ username: username.trim(), password }),
        });
        localStorage.setItem("nexus_token", data.access_token);
        onLogin(data.access_token);
      } else {
        const key = identifier.includes("@") ? "email" : "username";
        const data = await api("/auth/login", {
          method: "POST",
          body: JSON.stringify({ [key]: identifier.trim(), password }),
        });
        localStorage.setItem("nexus_token", data.access_token);
        onLogin(data.access_token);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return <main className="login-shell">
    <section className="login-card">
      <div className="brand-mark">N</div>
      <p className="eyebrow">PERSONAL OPERATING SYSTEM</p>
      <h1>NEXUS</h1>
      <p className="muted">{mode === "register" ? "Create your operating account." : "Plan. Execute. Track. Reflect. Improve."}</p>
      <form onSubmit={submit}>
        {mode === "register" ? (
          <>
            <label>Username<input value={username} onChange={e => setUsername(e.target.value)} required /></label>
            <label>Email<input type="email" value={email} onChange={e => setEmail(e.target.value)} required /></label>
          </>
        ) : (
          <label>Username or email<input value={identifier} onChange={e => setIdentifier(e.target.value)} required /></label>
        )}
        <label>Password<input type="password" value={password} onChange={e => setPassword(e.target.value)} minLength={8} required /></label>
        {error && <div className="error">{error}</div>}
        <button className="primary full" disabled={busy}>{busy ? "Working…" : mode === "register" ? "Create account" : "Enter NEXUS"}</button>
      </form>
      <button className="auth-switch" type="button" onClick={() => { setError(""); setMode(current => current === "login" ? "register" : "login"); }}>
        {mode === "register" ? "Already have an account? Sign in" : "New to NEXUS? Create an account"}
      </button>
    </section>
  </main>;
}

function App() {
  const [token, setToken] = useState(localStorage.getItem("nexus_token"));
  const [profile, setProfile] = useState(null);
  const [checkingProfile, setCheckingProfile] = useState(Boolean(token));

  useEffect(() => {
    if (!token) {
      setProfile(null);
      setCheckingProfile(false);
      return;
    }

    let cancelled = false;
    setCheckingProfile(true);
    api("/profile", {}, token)
      .then(data => {
        if (!cancelled) setProfile(data);
      })
      .catch(() => {
        if (!cancelled) {
          localStorage.removeItem("nexus_token");
          setToken(null);
          setProfile(null);
        }
      })
      .finally(() => {
        if (!cancelled) setCheckingProfile(false);
      });

    return () => { cancelled = true; };
  }, [token]);

  function logout() {
    localStorage.removeItem("nexus_token");
    setToken(null);
    setProfile(null);
  }

  if (!token) return <Login onLogin={setToken} />;
  if (checkingProfile) return <div className="loading">Loading NEXUS<span>•</span><span>•</span><span>•</span></div>;
  if (!profile?.onboarding_completed) {
    return <ProfileOnboarding token={token} onComplete={setProfile} />;
  }

  return <Dashboard token={token} onLogout={logout} />;
}

function Dashboard({ token, onLogout }) {
  const [view, setView] = useState("Overview");
  const [data, setData] = useState({ analytics: null, schedule: [], current: null, targets: [], habits: [], habitStats: [], history: [], activities: [], routines: [], diary: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [timerTitle, setTimerTitle] = useState("");
  const emptyActivityForm = { metric_value: "", topic: "", pattern: "", book: "", chapter: "", practice_type: "", workstream: "", milestone: "", accuracy: "", attempted: "", mistakes: "", words_learned: "", key_concepts: "", subject: "", difficulty: "", notes: "" };
  const [activityForm, setActivityForm] = useState(emptyActivityForm);
  const [now, setNow] = useState(Date.now());
  const [scheduleDate, setScheduleDate] = useState(localDate());

  const date = localDate();
  const month = `${date.slice(0, 7)}-01`;

  async function load() {
    try {
      setError("");
      const [analytics, schedule, current, targets, habits, habitStats, history, activities, routines, diary] = await Promise.all([
        api(`/analytics/summary?start_date=${date}&end_date=${date}`, {}, token),
        api(`/schedule?scheduled_date=${date}`, {}, token),
        api("/time-sessions/current", {}, token),
        api(`/targets?month=${month}`, {}, token),
        api("/habits", {}, token),
        api(`/habits/stats?start_date=${date}&end_date=${date}`, {}, token),
        api("/time-sessions", {}, token),
        api("/activity-records", {}, token),
        api("/routines", {}, token),
        api(`/diary?entry_date=${date}`, {}, token),
      ]);
      setData({ analytics, schedule, current, targets, habits, habitStats, history, activities, routines, diary });
      if (current) setTimerTitle(current.title);
    } catch (err) {
      setError(err.message);
      if (/token|authenticated|credentials/i.test(err.message)) onLogout();
    } finally { setLoading(false); }
  }

  useEffect(() => { load(); }, []);
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  async function startTimer() {
    if (!timerTitle.trim()) return;
    try {
      await api("/time-sessions/start", { method: "POST", body: JSON.stringify({ title: timerTitle.trim() }) }, token);
      await load();
    } catch (err) { setError(err.message); }
  }

  async function startSchedule(item) {
    try {
      await api("/time-sessions/start", {
        method: "POST",
        body: JSON.stringify({
          title: item.title,
          notes: item.notes || null,
          schedule_item_id: item.id,
          task_id: item.task_id,
          habit_id: item.habit_id,
          project_id: item.project_id,
          target_id: item.target_id
        })
      }, token);
      setView("Overview");
      await load();
    } catch (err) { setError(err.message); }
  }

  async function stopTimer() {
    if (!data.current) return;
    try {
      await api("/time-sessions/" + data.current.id + "/stop", { method: "POST" }, token);
      setActivityForm(emptyActivityForm);
      await load();
      setView("History");
    } catch (err) { setError(err.message); }
  }

  async function saveActivity(session, form, metricType) {
    const value = Number(form.metric_value);
    if (!Number.isFinite(value) || value < 0) throw new Error("Enter a valid measured value.");
    const details = { metric_type: metricType, duration_seconds: session.duration_seconds, ...Object.fromEntries(Object.entries(form).filter(([key, val]) => key !== "metric_value" && key !== "notes" && val !== "")) };
    details[metricKey(metricType)] = value;
    await api("/activity-records", { method: "POST", body: JSON.stringify({ activity_type: "execution", metric_type: metricType, title: session.title, details, notes: form.notes || null, time_session_id: session.id, task_id: session.task_id, habit_id: session.habit_id, project_id: session.project_id, target_id: session.target_id, metric_value: value }) }, token);
    await load();
  }

  async function updateScheduleTarget(item, targetId, refreshDate = null) {
    try {
      await api(`/schedule/${item.id}`, { method: "PATCH", body: JSON.stringify({ target_id: targetId || null }) }, token);
      if (refreshDate) await loadScheduleFor(refreshDate);
      else await load();
    } catch (err) { setError(err.message); }
  }

  async function markSchedule(item, status, refreshDate = null) {
    try {
      await api(`/schedule/${item.id}`, { method: "PATCH", body: JSON.stringify({ status }) }, token);
      if (refreshDate) await loadScheduleFor(refreshDate);
      else await load();
    } catch (err) { setError(err.message); }
  }

  async function createTarget(form) {
    await api("/targets", { method: "POST", body: JSON.stringify({
      title: form.title, description: form.description || null, month, metric_type: form.metric_type, target_value: Number(form.target_value)
    }) }, token);
    await load();
  }

  async function deleteTarget(target) {
    if (!window.confirm(`Delete target "${target.title}"?`)) return;
    try {
      await api("/targets/" + target.id, { method: "DELETE" }, token);
      await load();
    } catch (err) { setError(err.message); }
  }

  async function updateTarget(targetId, patch) {
    try {
      await api("/targets/" + targetId, { method: "PATCH", body: JSON.stringify(patch) }, token);
      await load();
    } catch (err) { setError(err.message); }
  }

  async function loadScheduleFor(selectedDate) {
    const schedule = await api(`/schedule?scheduled_date=${selectedDate}`, {}, token);
    setData(prev => ({ ...prev, schedule }));
  }

  async function createRoutine(form) {
    await api("/routines", { method: "POST", body: JSON.stringify({
      title: form.title, notes: form.notes || null, weekdays: form.weekdays.map(Number),
      start_time: form.start_time, end_time: form.end_time,
      habit_id: form.habit_id || null, target_id: form.target_id || null,
      priority: Number(form.priority), active: true
    }) }, token);
    await load();
  }

  async function generateRoutine(targetDate) {
    await api("/routines/generate/" + targetDate, { method: "POST" }, token);
    await loadScheduleFor(targetDate);
    setView("Schedule");
    setScheduleDate(targetDate);
  }

  async function createSchedule(form) {
    await api("/schedule", { method: "POST", body: JSON.stringify({
      title: form.title, notes: form.notes || null, scheduled_date: form.scheduled_date,
      start_at: isoFromLocal(form.start_at), end_at: isoFromLocal(form.end_at),
      priority: Number(form.priority), target_id: form.target_id || null, status: "planned"
    }) }, token);
    await loadScheduleFor(form.scheduled_date);
  }

  async function createHabit(form) {
    await api("/habits", { method: "POST", body: JSON.stringify({
      name: form.name, description: form.description || null, category: form.category || "general", frequency: form.frequency || "daily", metric_type: form.metric_type || "count"
    }) }, token);
    await load();
  }

  async function createDiary(form, existing) {
    const body = {
      accomplishments: form.accomplishments || null, what_went_badly: form.what_went_badly || null,
      learned: form.learned || null, feelings: form.feelings || null, distractions: form.distractions || null,
      tomorrow_changes: form.tomorrow_changes || null, free_writing: form.free_writing || null
    };
    if (existing) await api(`/diary/${existing.id}`, { method: "PATCH", body: JSON.stringify(body) }, token);
    else await api("/diary", { method: "POST", body: JSON.stringify({ entry_date: date, ...body }) }, token);
    await load();
  }

  const actualRunning = data.current ? Math.max(0, Math.floor((now - new Date(data.current.started_at).getTime()) / 1000)) : 0;
  const totals = data.analytics?.totals || {};
  const targets = data.targets.map(t => ({
    ...t, progress_percent: t.target_value ? Math.min(100, t.current_value / t.target_value * 100) : 0
  }));
  const greeting = useMemo(() => {
    const h = new Date().getHours();
    return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
  }, []);

  if (loading) return <div className="loading">Loading NEXUS<span>•</span><span>•</span><span>•</span></div>;

  const nav = ["Overview", "Routine", "Schedule", "Habits", "Targets", "History", "Analytics", "Diary"];

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="logo"><span>N</span><strong>NEXUS</strong></div>
      <div className="side-label">COMMAND CENTER</div>
      <nav>{nav.map(item => <button key={item} className={view === item ? "active" : ""} onClick={() => setView(item)}>{item}</button>)}</nav>
      <div className="side-bottom"><div className="system-status"><i /> System online</div><button className="ghost" onClick={onLogout}>Log out</button></div>
    </aside>

    <main className="main">
      <header className="topbar">
        <div><p className="eyebrow">{date}</p><h2>{greeting}. <span>{view === "Overview" ? "Let's execute." : view}</span></h2></div>
        <button className="icon-btn" onClick={load} title="Refresh">↻</button>
      </header>
      {error && <div className="error banner">{error}</div>}

      {view === "Overview" && <Overview data={data} targets={targets} actualRunning={actualRunning} timerTitle={timerTitle} setTimerTitle={setTimerTitle} startTimer={startTimer} stopTimer={stopTimer} activityForm={activityForm} setActivityForm={setActivityForm} markSchedule={markSchedule} onTargetChange={updateScheduleTarget} totals={totals} />}
      {view === "Routine" && <RoutineView date={scheduleDate} routines={data.routines} habits={data.habits} targets={data.targets} onCreate={createRoutine} onGenerate={generateRoutine} />}
      {view === "Schedule" && <ScheduleView date={scheduleDate} schedule={data.schedule} targets={data.targets} onDateChange={async (next) => { setScheduleDate(next); await loadScheduleFor(next); }} onCreate={createSchedule} onUpdate={(item, status) => markSchedule(item, status, scheduleDate)} onTargetChange={(item, targetId) => updateScheduleTarget(item, targetId, scheduleDate)} onStart={startSchedule} />}
      {view === "Habits" && <HabitsView habits={data.habits} habitStats={data.habitStats} onCreate={createHabit} />}
      {view === "Targets" && <TargetsView targets={targets} onCreate={createTarget} onUpdate={updateTarget} onDelete={deleteTarget} />}
      {view === "History" && <HistoryView history={data.history} activities={data.activities} targets={data.targets} habits={data.habits} onReview={saveActivity} />}
      {view === "Analytics" && <AnalyticsView token={token} />}
      {view === "Diary" && <DiaryView date={date} existing={data.diary[0]} onSave={createDiary} />}
    </main>
  </div>;
}

function Overview({ data, targets, actualRunning, timerTitle, setTimerTitle, startTimer, stopTimer, activityForm, setActivityForm, markSchedule, onTargetChange, totals }) {
  return <>
    <section className="hero-grid">
      <div className={`timer-card ${data.current ? "running" : ""}`}>
        <div className="card-top"><span className="eyebrow">FOCUS TIMER</span><span className="live-dot">{data.current ? "RUNNING" : "READY"}</span></div>
        <div className="timer-value">{formatSeconds(data.current ? actualRunning : 0)}</div>
        {data.current ? <><div className="timer-title">{data.current.title}</div><p className="muted small">Time is tracked automatically. Review what you accomplished after stopping.</p><button className="danger full" onClick={stopTimer}>Stop session</button></>
          : <div className="timer-start"><input placeholder="What are you working on?" value={timerTitle} onChange={e => setTimerTitle(e.target.value)} onKeyDown={e => e.key === "Enter" && startTimer()} /><button className="primary" onClick={startTimer}>Start</button></div>}
      </div>
      <div className="stat-card"><span className="eyebrow">FOCUSED TODAY</span><strong>{formatSeconds(totals.actual_seconds)}</strong><p>Actual tracked time</p></div>
      <div className="stat-card"><span className="eyebrow">PLANNED</span><strong>{formatSeconds(totals.planned_seconds)}</strong><p>{totals.planned_items || 0} scheduled blocks</p></div>
      <div className="stat-card"><span className="eyebrow">EXECUTION</span><strong>{totals.schedule_completion_rate || 0}%</strong><p>{totals.completed_items || 0} of {totals.planned_items || 0} completed</p></div>
    </section>
    <section className="content-grid">
      <div className="panel schedule-panel"><div className="panel-head"><div><span className="eyebrow">TODAY</span><h3>Execution schedule</h3></div><span className="count">{data.schedule.length}</span></div>
        {data.schedule.length === 0 ? <Empty text="Nothing scheduled yet. Use Schedule to plan your day." /> : <div className="schedule-list">{data.schedule.map(item => <div className={`schedule-row ${item.status}`} key={item.id}>
          <div className="time">{formatClock(item.start_at)}<small>{formatClock(item.end_at)}</small></div>
          <div className="schedule-info"><strong>{item.title}</strong><span>{item.notes || "Focus block"}</span><select className="schedule-target" value={item.target_id || ""} onChange={e => onTargetChange(item, e.target.value)}><option value="">No target</option>{targets.map(t => <option key={t.id} value={t.id}>{t.title} · {METRIC_LABELS[t.metric_type] || t.metric_type}</option>)}</select></div>
          <div className="row-actions">{(item.status === "planned" || item.status === "partial") && <><button onClick={() => markSchedule(item, "completed")}>Done</button>{item.status === "planned" && <button onClick={() => markSchedule(item, "skipped")}>Skip</button>}</>}</div>
        </div>)}</div>}
      </div>
      <div className="panel"><div className="panel-head"><div><span className="eyebrow">OCTOBER</span><h3>Targets</h3></div></div>
        {targets.length === 0 ? <Empty text="No monthly targets yet." /> : targets.slice(0, 4).map(t => <TargetCard key={t.id} t={t} />)}
      </div>
    </section>
    <section className="panel metrics"><div className="panel-head"><div><span className="eyebrow">TODAY</span><h3>Operating pulse</h3></div></div>
      <div className="metric-grid"><Metric label="Activities" value={totals.activity_count || 0} /><Metric label="Sessions" value={totals.session_count || 0} /><Metric label="Diary" value={totals.diary_days || 0} /><Metric label="Skipped" value={totals.skipped_items || 0} /></div>
    </section>
  </>;
}


function MetricCapture({ target, form, setForm }) {
  if (!target) return null;
  const update = (key, value) => setForm(prev => ({ ...prev, [key]: value }));
  const valueLabels = {
    problems_solved: "Problems solved",
    pages_read: "Pages read",
    sessions_completed: "Sessions completed",
    questions_solved: "Questions solved",
    topics_revised: "Topics revised",
    milestones_completed: "Milestones completed",
    books_completed: "Books completed",
    count: "Completed count",
  };
  return <div className="activity-capture">
    <div className="capture-title">Record {METRIC_LABELS[target.metric_type]}</div>
    <label>{valueLabels[target.metric_type] || "Measured value"}<input type="number" min="0" value={form.metric_value} onChange={e => update("metric_value", e.target.value)} required /></label>
    {target.metric_type === "problems_solved" && <div className="capture-grid">
      <label>Topic<input value={form.topic} onChange={e=>update("topic",e.target.value)} /></label>
      <label>Pattern<input value={form.pattern} onChange={e=>update("pattern",e.target.value)} placeholder="Sliding window, hashing…" /></label>
      <label>Attempted<input type="number" min="0" value={form.attempted} onChange={e=>update("attempted",e.target.value)} /></label>
      <label>Mistakes<input type="number" min="0" value={form.mistakes} onChange={e=>update("mistakes",e.target.value)} /></label>
      <label>Difficulty<input value={form.difficulty} onChange={e=>update("difficulty",e.target.value)} placeholder="Easy / Medium / Hard" /></label>
    </div>}
    {target.metric_type === "pages_read" && <div className="capture-grid">
      <label>Book<input value={form.book} onChange={e=>update("book",e.target.value)} /></label>
      <label>Chapter<input value={form.chapter} onChange={e=>update("chapter",e.target.value)} /></label>
      <label>Key concepts<textarea value={form.key_concepts} onChange={e=>update("key_concepts",e.target.value)} /></label>
    </div>}
    {target.metric_type === "sessions_completed" && <div className="capture-grid">
      <label>Practice type<input value={form.practice_type} onChange={e=>update("practice_type",e.target.value)} placeholder="Speaking / writing / pronunciation" /></label>
      <label>Topic<input value={form.topic} onChange={e=>update("topic",e.target.value)} /></label>
      <label>Words learned<input type="number" min="0" value={form.words_learned} onChange={e=>update("words_learned",e.target.value)} /></label>
      <label>Accuracy %<input type="number" min="0" max="100" value={form.accuracy} onChange={e=>update("accuracy",e.target.value)} /></label>
    </div>}
    {target.metric_type === "questions_solved" && <div className="capture-grid">
      <label>Subject<input value={form.subject} onChange={e=>update("subject",e.target.value)} /></label>
      <label>Topic<input value={form.topic} onChange={e=>update("topic",e.target.value)} /></label>
      <label>Accuracy %<input type="number" min="0" max="100" value={form.accuracy} onChange={e=>update("accuracy",e.target.value)} /></label>
    </div>}
    {target.metric_type === "topics_revised" && <div className="capture-grid">
      <label>Subject<input value={form.subject} onChange={e=>update("subject",e.target.value)} /></label>
      <label>Revision topic<input value={form.topic} onChange={e=>update("topic",e.target.value)} /></label>
      <label>Questions solved<input type="number" min="0" value={form.attempted} onChange={e=>update("attempted",e.target.value)} /></label>
      <label>Accuracy %<input type="number" min="0" max="100" value={form.accuracy} onChange={e=>update("accuracy",e.target.value)} /></label>
    </div>}
    {target.metric_type === "milestones_completed" && <div className="capture-grid">
      <label>Workstream<input value={form.workstream} onChange={e=>update("workstream",e.target.value)} /></label>
      <label>Milestone<input value={form.milestone} onChange={e=>update("milestone",e.target.value)} /></label>
    </div>}
    {target.metric_type === "books_completed" && <div className="capture-grid">
      <label>Book<input value={form.book} onChange={e=>update("book",e.target.value)} /></label>
      <label>Key concepts<textarea value={form.key_concepts} onChange={e=>update("key_concepts",e.target.value)} /></label>
    </div>}
    {target.metric_type === "count" && <label>What did you accomplish?<textarea value={form.key_concepts} onChange={e=>update("key_concepts",e.target.value)} placeholder="Brief evidence of the work completed." /></label>}
    <label>Notes<textarea value={form.notes} onChange={e=>update("notes",e.target.value)} placeholder="Mistakes, decisions, next action, or anything worth remembering." /></label>
  </div>;
}

function TargetCard({ t }) {
  const p = t.progress_percent || 0;
  return <div className="target"><div className="target-line"><strong>{t.title}</strong><span>{t.current_value}/{t.target_value ?? "—"}</span></div><div className="progress"><i style={{ width: `${Math.min(100, p)}%` }} /></div><small>{METRIC_LABELS[t.metric_type] || t.metric_type} · {p.toFixed(0)}% complete</small></div>;
}

function RoutineView({ date, routines, habits, targets, onCreate, onGenerate }) {
  const days=["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"];
  const [form, setForm] = useState({ title:"", notes:"", weekdays:[0,1,2,3,4,5,6], start_time:"04:30", end_time:"05:30", habit_id:"", target_id:"", priority:3 });
  const toggleDay = (day) => setForm(prev => ({...prev, weekdays: prev.weekdays.includes(day) ? prev.weekdays.filter(d=>d!==day) : [...prev.weekdays, day].sort((a,b)=>a-b)}));
  const submit=async e=>{e.preventDefault(); if(!form.weekdays.length) return; await onCreate(form); setForm({...form,title:"",notes:"",habit_id:"",target_id:""});};
  return <section className="two-col">
    <div className="panel"><PanelTitle eyebrow="CORE ROUTINE" title="Build your recurring timetable" /><p className="muted small">Define each block once, choose the days it repeats, then generate that day's schedule. Emergencies or special events are changed only in Schedule.</p>
      <form className="form-grid" onSubmit={submit}>
        <label>Block title<input value={form.title} onChange={e=>setForm({...form,title:e.target.value})} placeholder="DSA Practice" required /></label>
        <label>Notes<textarea value={form.notes} onChange={e=>setForm({...form,notes:e.target.value})}/></label>
        <div><span className="field-label">REPEAT ON</span><div className="day-picker">{days.map((d,i)=><label className="day-option" key={i}><input type="checkbox" checked={form.weekdays.includes(i)} onChange={()=>toggleDay(i)} /><span>{d.slice(0,3)}</span></label>)}</div></div>
        <div className="inline-fields"><label>Start<input type="time" value={form.start_time} onChange={e=>setForm({...form,start_time:e.target.value})} required /></label><label>End<input type="time" value={form.end_time} onChange={e=>setForm({...form,end_time:e.target.value})} required /></label></div>
        <label>Habit<select value={form.habit_id} onChange={e=>setForm({...form,habit_id:e.target.value})}><option value="">No habit</option>{habits.map(h=><option key={h.id} value={h.id}>{h.name}</option>)}</select></label>
        <label>Monthly target<select value={form.target_id} onChange={e=>setForm({...form,target_id:e.target.value})}><option value="">No target</option>{targets.map(t=><option key={t.id} value={t.id}>{t.title}</option>)}</select></label>
        <label>Priority<select value={form.priority} onChange={e=>setForm({...form,priority:e.target.value})}><option value="1">1 — Critical</option><option value="2">2 — High</option><option value="3">3 — Normal</option><option value="4">4 — Low</option><option value="5">5 — Lowest</option></select></label>
        <button className="primary">Add recurring block</button>
      </form>
    </div>
    <div className="panel"><PanelTitle eyebrow="YOUR ROUTINE" title="Recurring blocks" />
      {routines.length ? <div className="schedule-list">{routines.map(r=><RoutineRow key={r.id} routine={r} days={days} habits={habits} targets={targets} />)}</div> : <Empty text="No core routine blocks yet." />}
      <button className="primary full" onClick={()=>onGenerate(date)}>Generate {date} from routine</button>
    </div>
  </section>;
}

function RoutineRow({ routine, days, habits, targets }) {
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({ title:routine.title, notes:routine.notes||"", weekdays:routine.weekdays||[], start_time:routine.start_time.slice(0,5), end_time:routine.end_time.slice(0,5), habit_id:routine.habit_id||"", target_id:routine.target_id||"", priority:routine.priority });
  const toggleDay = (day) => setForm(prev => ({...prev, weekdays: prev.weekdays.includes(day) ? prev.weekdays.filter(d=>d!==day) : [...prev.weekdays, day].sort((a,b)=>a-b)}));
  const update = async () => {
    if(!form.weekdays.length) return;
    const token = localStorage.getItem("nexus_token");
    const payload = {...form, weekdays:form.weekdays.map(Number), priority:Number(form.priority), habit_id:form.habit_id||null, target_id:form.target_id||null};
    const response = await fetch(API+"/routines/"+routine.id,{method:"PATCH",headers:{"Content-Type":"application/json",Authorization:"Bearer "+token},body:JSON.stringify(payload)});
    if(!response.ok) throw new Error("Failed to update routine.");
    window.location.reload();
  };
  const remove = async () => {
    if(!window.confirm("Delete this recurring routine block?")) return;
    const token = localStorage.getItem("nexus_token");
    const response = await fetch(API+"/routines/"+routine.id,{method:"DELETE",headers:{Authorization:"Bearer "+token}});
    if(!response.ok) throw new Error("Failed to delete routine.");
    window.location.reload();
  };
  if(editing) return <div className="panel routine-edit-row"><div className="form-grid">
    <label>Title<input value={form.title} onChange={e=>setForm({...form,title:e.target.value})}/></label>
    <label>Notes<textarea value={form.notes} onChange={e=>setForm({...form,notes:e.target.value})}/></label>
    <div><span className="field-label">REPEAT ON</span><div className="day-picker">{days.map((d,i)=><label className="day-option" key={i}><input type="checkbox" checked={form.weekdays.includes(i)} onChange={()=>toggleDay(i)}/><span>{d.slice(0,3)}</span></label>)}</div></div>
    <div className="inline-fields"><label>Start<input type="time" value={form.start_time} onChange={e=>setForm({...form,start_time:e.target.value})}/></label><label>End<input type="time" value={form.end_time} onChange={e=>setForm({...form,end_time:e.target.value})}/></label></div>
    <label>Habit<select value={form.habit_id} onChange={e=>setForm({...form,habit_id:e.target.value})}><option value="">No habit</option>{habits.map(h=><option key={h.id} value={h.id}>{h.name}</option>)}</select></label>
    <label>Target<select value={form.target_id} onChange={e=>setForm({...form,target_id:e.target.value})}><option value="">No target</option>{targets.map(t=><option key={t.id} value={t.id}>{t.title}</option>)}</select></label>
    <div className="row-actions"><button onClick={update}>Save</button><button onClick={()=>setEditing(false)}>Cancel</button><button className="danger-text" onClick={remove}>Delete</button></div>
  </div></div>;
  const dayLabel=(routine.weekdays||[]).map(i=>days[i]?.slice(0,3)).filter(Boolean);
  return <div className="routine-row"><div className="routine-days">{dayLabel.map((day,index)=><span className="routine-day active" key={index}>{day}</span>)}</div><div className="schedule-info"><strong>{routine.title}</strong><span>{routine.start_time.slice(0,5)}–{routine.end_time.slice(0,5)} · {routine.habit_id?"Habit linked":"Routine block"}{routine.target_id?" · Target linked":""}</span></div><div className="row-actions"><button onClick={()=>setEditing(true)}>Edit</button><button className="danger-text" onClick={remove}>Delete</button></div></div>;
}

function ScheduleView({ date, schedule, targets, onDateChange, onCreate, onUpdate, onTargetChange, onStart }) {
  const [form, setForm] = useState({ title: "", notes: "", scheduled_date: date, start_at: `${date}T18:00`, end_at: `${date}T19:00`, priority: 3, target_id: "" });
  useEffect(() => {
    setForm(prev => ({ ...prev, scheduled_date: date, start_at: `${date}T18:00`, end_at: `${date}T19:00` }));
  }, [date]);
  const shiftDate = (days) => {
    const d = new Date(`${date}T12:00:00`);
    d.setDate(d.getDate() + days);
    onDateChange(localDate(d));
  };
  const dateLabel = new Date(`${date}T12:00:00`).toLocaleDateString([], { weekday: "long", month: "short", day: "numeric", year: "numeric" });
  const submit = async e => { e.preventDefault(); await onCreate(form); setForm({ ...form, title: "", notes: "", target_id: "" }); };
  return <section className="two-col"><div className="panel"><PanelTitle eyebrow="PLAN" title="Add schedule block" /><form className="form-grid" onSubmit={submit}>
    <label>Title<input value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} required /></label>
    <label>Notes<textarea value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} /></label>
    <label>Date<input type="date" value={form.scheduled_date} onChange={e => { const d=e.target.value; setForm({ ...form, scheduled_date:d, start_at:`${d}T18:00`, end_at:`${d}T19:00` }); }} required /></label>
    <div className="inline-fields"><label>Start<input type="datetime-local" value={form.start_at} onChange={e => setForm({ ...form, start_at:e.target.value })} required /></label><label>End<input type="datetime-local" value={form.end_at} onChange={e => setForm({ ...form, end_at:e.target.value })} required /></label></div>
    <label>Target<select value={form.target_id} onChange={e => setForm({ ...form, target_id:e.target.value })}><option value="">No target</option>{targets.map(t => <option key={t.id} value={t.id}>{t.title}</option>)}</select></label><label>Priority<select value={form.priority} onChange={e => setForm({ ...form, priority:e.target.value })}><option value="1">1 — Critical</option><option value="2">2 — High</option><option value="3">3 — Normal</option><option value="4">4 — Low</option><option value="5">5 — Lowest</option></select></label>
    <button className="primary">Add to schedule</button>
  </form></div><div className="panel"><div className="panel-head"><div><span className="eyebrow">{date}</span><h3>{date === localDate() ? "Today’s plan" : "Planned execution"}</h3><p className="muted small">{dateLabel}</p></div><div className="date-nav"><button className="ghost small-btn" type="button" onClick={() => shiftDate(-1)}>←</button><button className="ghost small-btn" type="button" onClick={() => shiftDate(1)}>→</button></div></div><div className="schedule-list">{schedule.length ? schedule.map(item => <div className={`schedule-row ${item.status}`} key={item.id}><div className="time">{formatClock(item.start_at)}<small>{formatClock(item.end_at)}</small></div><div className="schedule-info"><strong>{item.title}</strong><span>{item.notes || "Focus block"}{item.target_id && " · Target linked"}{item.status === "partial" && " · Partial"}</span></div><div className="row-actions">{(item.status === "planned" || item.status === "partial") && <><button onClick={() => onStart(item)}>Start</button><button onClick={() => onUpdate(item,"completed")}>Done</button>{item.status === "planned" && <button onClick={() => onUpdate(item,"skipped")}>Skip</button>}</>}</div></div>) : <Empty text="No blocks planned." />}</div></div></section>;
}

function HabitsView({ habits, habitStats, onCreate }) {
  const [form, setForm] = useState({ name:"", description:"", category:"study", frequency:"daily", metric_type:"count" });
  const submit = async e => { e.preventDefault(); await onCreate(form); setForm({ name:"", description:"", category:"study", frequency:"daily", metric_type:"count" }); };
  return <section className="two-col"><div className="panel"><PanelTitle eyebrow="ROUTINE" title="Create habit" /><form className="form-grid" onSubmit={submit}><label>Name<input value={form.name} onChange={e=>setForm({...form,name:e.target.value})} required /></label><label>Description<textarea value={form.description} onChange={e=>setForm({...form,description:e.target.value})}/></label><label>Category<input value={form.category} onChange={e=>setForm({...form,category:e.target.value})}/></label><label>Frequency<select value={form.frequency} onChange={e=>setForm({...form,frequency:e.target.value})}><option>daily</option><option>weekly</option><option>custom</option></select></label><label>Activity metric<select value={form.metric_type} onChange={e=>setForm({...form,metric_type:e.target.value})}>{METRIC_OPTIONS.map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label><button className="primary">Create habit</button></form></div><div className="panel"><PanelTitle eyebrow="ACTIVE" title="Your habits" />{habits.length ? <div className="item-list">{habits.map(h=>{ const s=habitStats.find(x=>x.habit_id===h.id); return <div className="list-item" key={h.id}><div><strong>{h.name}</strong><span>{h.category} · {h.frequency} · {METRIC_LABELS[h.metric_type] || "Generic count"}</span>{s && <span>{s.completed_count}/{s.expected_count} days · {s.consistency_percent}% consistency · {s.current_streak} day streak · {formatSeconds(s.focused_seconds)}</span>}</div><b>{h.active ? "ACTIVE" : "OFF"}</b></div>;})}</div> : <Empty text="No habits yet." />}</div></section>;
}

function TargetsView({ targets, onCreate, onUpdate, onDelete }) {
  const [form, setForm] = useState({ title:"", description:"", metric_type:"auto", target_value:"" });
  const submit = async e => {
    e.preventDefault();
    await onCreate({ ...form, metric_type: form.metric_type === "auto" ? inferMetricType(form.title) : form.metric_type });
    setForm({ title:"", description:"", metric_type:"auto", target_value:"" });
  };
  const selectedMetric = form.metric_type === "auto" ? inferMetricType(form.title) : form.metric_type;
  return <section className="two-col">
    <div className="panel">
      <PanelTitle eyebrow="MONTHLY COMMITMENT" title="Add October target" />
      <form className="form-grid" onSubmit={submit}>
        <label>Target<input value={form.title} onChange={e=>setForm({...form,title:e.target.value})} placeholder="e.g. Solve 150 DSA problems" required /></label>
        <label>Description<textarea value={form.description} onChange={e=>setForm({...form,description:e.target.value})}/></label>
        <label>Progress metric<select value={selectedMetric} onChange={e=>setForm({...form,metric_type:e.target.value})}>{METRIC_OPTIONS.map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label>
        <label>Target value<input type="number" min="0" value={form.target_value} onChange={e=>setForm({...form,target_value:e.target.value})} required /></label>
        <button className="primary">Create target</button>
      </form>
    </div>
    <div className="panel">
      <PanelTitle eyebrow="OCTOBER" title="Targets" />
      {targets.length ? targets.map(t=><TargetEditor key={t.id} target={t} onUpdate={onUpdate} onDelete={onDelete} />) : <Empty text="No monthly targets yet." />}
    </div>
  </section>;
}

function TargetEditor({ target, onUpdate, onDelete }) {
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({ title:target.title, description:target.description||"", metric_type:target.metric_type||"count", target_value:target.target_value??0 });
  const save = async () => { await onUpdate(target.id, { title:form.title, description:form.description||null, metric_type:form.metric_type, target_value:Number(form.target_value) }); setEditing(false); };
  if (editing) return <div className="target-editor">
    <label>Title<input value={form.title} onChange={e=>setForm({...form,title:e.target.value})}/></label>
    <label>Description<textarea value={form.description} onChange={e=>setForm({...form,description:e.target.value})}/></label>
    <label>Progress metric<select value={form.metric_type} onChange={e=>setForm({...form,metric_type:e.target.value})}>{METRIC_OPTIONS.map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label>
    <label>Target value<input type="number" min="0" value={form.target_value} onChange={e=>setForm({...form,target_value:e.target.value})}/></label>
    <div className="row-actions"><button className="primary" onClick={save}>Save</button><button onClick={()=>setEditing(false)}>Cancel</button><button className="danger-text" onClick={()=>onDelete(target)}>Delete</button></div>
  </div>;
  return <div className="target-card-row">
    <TargetCard t={target}/>
    <div className="row-actions">
      <button onClick={()=>setEditing(true)}>Edit</button>
      <button className="danger-text" onClick={()=>onDelete(target)}>Delete</button>
    </div>
  </div>;
}

function HistoryView({ history, activities, targets, habits, onReview }) {
  return <section className="panel"><PanelTitle eyebrow="EXECUTION LOG" title="Completed sessions" />
    {history.length ? <div className="history-list">{history.map(s => {
      const reviewed = activities.some(a => a.time_session_id === s.id);
      const target = s.target_id ? targets.find(t => t.id === s.target_id) : null;
      const habit = s.habit_id ? habits.find(h => h.id === s.habit_id) : null;
      const metricType = target?.metric_type || habit?.metric_type || "count";
      return <HistoryRow key={s.id} session={s} reviewed={reviewed} target={target} habit={habit} metricType={metricType} onReview={onReview} />;
    })}</div> : <Empty text="No completed sessions yet. Start your first focus session." />}</section>;
}

function HistoryRow({ session, reviewed, target, habit, metricType, onReview }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ metric_value:"", topic:"", book:"", chapter:"", practice_type:"", workstream:"", milestone:"", accuracy:"", attempted:"", mistakes:"", words_learned:"", key_concepts:"", subject:"", difficulty:"" });
  const submit = async e => { e.preventDefault(); try { await onReview(session, form, metricType); setOpen(false); } catch (err) { alert(err.message); } };
  return <div className="history-row history-review-row">
    <div><strong>{session.title}</strong><span>{new Date(session.started_at).toLocaleDateString()} · {new Date(session.started_at).toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"})} · {formatSeconds(session.duration_seconds)}</span><span>{target ? "Target: " + target.title : habit ? "Habit: " + habit.name : "Unlinked session"}</span></div>
    {reviewed ? <b>REVIEWED</b> : <button onClick={() => setOpen(v => !v)}>{open ? "Close" : "Review"}</button>}
    {open && !reviewed && <div className="review-box"><MetricCapture target={{ metric_type: metricType }} form={form} setForm={setForm} /><button className="primary" onClick={submit}>Save activity review</button></div>}
  </div>;
}
function DiaryView({ date, existing, onSave }) {
  const [form, setForm] = useState({
    accomplishments: existing?.accomplishments || "", what_went_badly: existing?.what_went_badly || "", learned: existing?.learned || "",
    feelings: existing?.feelings || "", distractions: existing?.distractions || "", tomorrow_changes: existing?.tomorrow_changes || "", free_writing: existing?.free_writing || ""
  });
  useEffect(()=>setForm({ accomplishments: existing?.accomplishments || "", what_went_badly: existing?.what_went_badly || "", learned: existing?.learned || "", feelings: existing?.feelings || "", distractions: existing?.distractions || "", tomorrow_changes: existing?.tomorrow_changes || "", free_writing: existing?.free_writing || "" }),[existing?.id]);
  const field=(key,label,placeholder)=><label>{label}<textarea value={form[key]} placeholder={placeholder} onChange={e=>setForm({...form,[key]:e.target.value})}/></label>;
  return <section className="panel diary-panel"><PanelTitle eyebrow={date} title={existing ? "Daily reflection" : "Write today's reflection"} /><p className="muted small">5–10 minutes. Record evidence, not a performance report.</p><form className="form-grid diary-grid" onSubmit={async e=>{e.preventDefault();await onSave(form,existing);}}>{field("accomplishments","What did you accomplish?","What moved forward today?")}{field("what_went_badly","What went badly?","Where did time or focus leak?")}{field("learned","What did you learn?","Concepts, mistakes, insights.")}{field("feelings","How did you feel?","Focused, tired, confident, frustrated…")}{field("distractions","Distractions","What pulled you away?")}{field("tomorrow_changes","What changes tomorrow?","One concrete adjustment.")}{field("free_writing","Free writing","Anything else worth remembering.")}<button className="primary">{existing ? "Update reflection" : "Save reflection"}</button></form></section>;
}

function PanelTitle({ eyebrow, title }) { return <div className="panel-head"><div><span className="eyebrow">{eyebrow}</span><h3>{title}</h3></div></div>; }
function Metric({ label, value }) { return <div className="metric"><span>{label}</span><strong>{value}</strong></div>; }
function Empty({ text }) { return <div className="empty">{text}</div>; }

export default App;
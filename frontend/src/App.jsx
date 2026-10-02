import { useEffect, useMemo, useState } from "react";

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

const today = () => new Date().toISOString().slice(0, 10);
const formatSeconds = (s = 0) => {
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return h ? `${h}h ${m}m` : m ? `${m}m` : `${sec}s`;
};
const formatClock = (iso) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

function Login({ onLogin }) {
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(e) {
    e.preventDefault(); setBusy(true); setError("");
    try {
      const key = identifier.includes("@") ? "email" : "username";
      const data = await api("/auth/login", {
        method: "POST",
        body: JSON.stringify({ [key]: identifier, password }),
      });
      localStorage.setItem("nexus_token", data.access_token);
      onLogin(data.access_token);
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  }

  return <main className="login-shell">
    <section className="login-card">
      <div className="brand-mark">N</div>
      <p className="eyebrow">PERSONAL OPERATING SYSTEM</p>
      <h1>NEXUS</h1>
      <p className="muted">Plan. Execute. Track. Reflect. Improve.</p>
      <form onSubmit={submit}>
        <label>Username or email<input value={identifier} onChange={e => setIdentifier(e.target.value)} required /></label>
        <label>Password<input type="password" value={password} onChange={e => setPassword(e.target.value)} required /></label>
        {error && <div className="error">{error}</div>}
        <button className="primary full" disabled={busy}>{busy ? "Signing in…" : "Enter NEXUS"}</button>
      </form>
    </section>
  </main>;
}

function App() {
  const [token, setToken] = useState(localStorage.getItem("nexus_token"));
  return token
    ? <Dashboard token={token} onLogout={() => { localStorage.removeItem("nexus_token"); setToken(null); }} />
    : <Login onLogin={setToken} />;
}

function Dashboard({ token, onLogout }) {
  const [data, setData] = useState({ analytics: null, schedule: [], current: null, targets: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [timerTitle, setTimerTitle] = useState("");
  const [now, setNow] = useState(Date.now());

  const date = today();

  async function load() {
    try {
      setError("");
      const [analytics, schedule, current, targets] = await Promise.all([
        api(`/analytics/summary?start_date=${date}&end_date=${date}`, {}, token),
        api(`/schedule?scheduled_date=${date}`, {}, token),
        api("/time-sessions/current", {}, token),
        api(`/targets?month=${date.slice(0,7)}-01`, {}, token),
      ]);
      setData({ analytics, schedule, current, targets });
      if (current && !timerTitle) setTimerTitle(current.title);
    } catch (err) {
      setError(err.message);
      if (err.message.toLowerCase().includes("token")) onLogout();
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
      await api("/time-sessions/start", {
        method: "POST", body: JSON.stringify({ title: timerTitle.trim() })
      }, token);
      await load();
    } catch (err) { setError(err.message); }
  }

  async function stopTimer() {
    if (!data.current) return;
    try { await api(`/time-sessions/${data.current.id}/stop`, { method: "POST" }, token); await load(); }
    catch (err) { setError(err.message); }
  }

  async function markSchedule(item, status) {
    try {
      await api(`/schedule/${item.id}`, { method: "PATCH", body: JSON.stringify({ status }) }, token);
      await load();
    } catch (err) { setError(err.message); }
  }

  const actualRunning = data.current
    ? Math.max(0, Math.floor((now - new Date(data.current.started_at).getTime()) / 1000))
    : 0;
  const totals = data.analytics?.totals || {};
  const targets = data.analytics?.target_progress || data.targets.map(t => ({
    ...t, progress_percent: t.target_value ? Math.min(100, t.current_value / t.target_value * 100) : 0
  }));

  const greeting = useMemo(() => {
    const h = new Date().getHours();
    return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
  }, []);

  if (loading) return <div className="loading">Loading NEXUS<span>•</span><span>•</span><span>•</span></div>;

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="logo"><span>N</span><strong>NEXUS</strong></div>
      <div className="side-label">COMMAND CENTER</div>
      <nav>
        <a className="active">Overview</a><a>Schedule</a><a>Habits</a><a>Targets</a><a>History</a><a>Diary</a>
      </nav>
      <div className="side-bottom">
        <div className="system-status"><i /> System online</div>
        <button className="ghost" onClick={onLogout}>Log out</button>
      </div>
    </aside>

    <main className="main">
      <header className="topbar">
        <div><p className="eyebrow">{date}</p><h2>{greeting}. <span>Let's execute.</span></h2></div>
        <button className="icon-btn" onClick={load} title="Refresh">↻</button>
      </header>

      {error && <div className="error banner">{error}</div>}

      <section className="hero-grid">
        <div className={`timer-card ${data.current ? "running" : ""}`}>
          <div className="card-top"><span className="eyebrow">FOCUS TIMER</span><span className="live-dot">{data.current ? "RUNNING" : "READY"}</span></div>
          <div className="timer-value">{formatSeconds(data.current ? actualRunning : 0)}</div>
          {data.current ? <><div className="timer-title">{data.current.title}</div><button className="danger full" onClick={stopTimer}>Stop session</button></>
            : <div className="timer-start"><input placeholder="What are you working on?" value={timerTitle} onChange={e => setTimerTitle(e.target.value)} onKeyDown={e => e.key === "Enter" && startTimer()} /><button className="primary" onClick={startTimer}>Start</button></div>}
        </div>
        <div className="stat-card"><span className="eyebrow">FOCUSED TODAY</span><strong>{formatSeconds(totals.actual_seconds)}</strong><p>Actual tracked time</p></div>
        <div className="stat-card"><span className="eyebrow">PLANNED</span><strong>{formatSeconds(totals.planned_seconds)}</strong><p>{totals.planned_items || 0} scheduled blocks</p></div>
        <div className="stat-card"><span className="eyebrow">EXECUTION</span><strong>{totals.schedule_completion_rate || 0}%</strong><p>{totals.completed_items || 0} of {totals.planned_items || 0} completed</p></div>
      </section>

      <section className="content-grid">
        <div className="panel schedule-panel">
          <div className="panel-head"><div><span className="eyebrow">TODAY</span><h3>Execution schedule</h3></div><span className="count">{data.schedule.length}</span></div>
          {data.schedule.length === 0 ? <Empty text="Nothing scheduled yet." /> : <div className="schedule-list">
            {data.schedule.map(item => <div className={`schedule-row ${item.status}`} key={item.id}>
              <div className="time">{formatClock(item.start_at)}<small>{formatClock(item.end_at)}</small></div>
              <div className="schedule-info"><strong>{item.title}</strong><span>{item.notes || "Focus block"}</span></div>
              <div className="row-actions">{item.status === "planned" && <><button onClick={() => markSchedule(item, "completed")}>Done</button><button onClick={() => markSchedule(item, "skipped")}>Skip</button></>}</div>
            </div>)}
          </div>}
        </div>

        <div className="panel">
          <div className="panel-head"><div><span className="eyebrow">OCTOBER</span><h3>Targets</h3></div></div>
          {targets.length === 0 ? <Empty text="No monthly targets." /> : targets.map(t => <div className="target" key={t.id}>
            <div className="target-line"><strong>{t.title}</strong><span>{t.current_value}/{t.target_value ?? "—"}</span></div>
            <div className="progress"><i style={{ width: `${Math.min(100, t.progress_percent || 0)}%` }} /></div>
            <small>{t.progress_percent ?? 0}% complete</small>
          </div>)}
        </div>
      </section>

      <section className="panel metrics">
        <div className="panel-head"><div><span className="eyebrow">TODAY</span><h3>Operating pulse</h3></div></div>
        <div className="metric-grid">
          <Metric label="Activities" value={totals.activity_count || 0} />
          <Metric label="Sessions" value={totals.session_count || 0} />
          <Metric label="Diary" value={totals.diary_days || 0} />
          <Metric label="Skipped" value={totals.skipped_items || 0} />
        </div>
      </section>
    </main>
  </div>;
}

function Metric({ label, value }) { return <div className="metric"><span>{label}</span><strong>{value}</strong></div>; }
function Empty({ text }) { return <div className="empty">{text}</div>; }

export default App;
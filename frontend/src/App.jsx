import AnalyticsView from "./AnalyticsView";
import ActivityReview from "./ActivityReview";
import Ambitions from "./Ambitions";
import ProfileOnboarding from "./ProfileOnboarding";
import { addCalendarDays, AmbiguousProfileTimeError, isValidTimeZone, profileClock, profileDate, profileDateTimeInput, profileLocalTimeToISO } from "./plannerTimezone.js";
import React, { useEffect, useMemo, useState } from "react";

const API = `${(import.meta.env.VITE_API_URL || "http://127.0.0.1:8000").replace(/\/+$/, "")}/api/v1`;

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
    if (!r.ok) {
      const detail = data?.detail;
      const message = Array.isArray(detail)
        ? detail.map((item) => item?.msg || "Invalid input").join(" ")
        : typeof detail === "string"
          ? detail
          : typeof detail?.message === "string"
            ? detail.message
            : `Request failed (${r.status})`;
      const error = new Error(message);
      error.status = r.status;
      error.detail = detail;
      throw error;
    }
    return data;
  });
}

async function requestScheduleChange(path, options, token, timeZone) {
  try { return await api(path, options, token); }
  catch (error) {
    const conflicts = error.detail?.conflicts;
    if (error.status !== 409 || !Array.isArray(conflicts) || conflicts.length === 0) throw error;
    const names = conflicts.map(item => `${item.title} (${profileClock(item.start_at, timeZone)}–${profileClock(item.end_at, timeZone)})`).join("\n");
    if (!window.confirm(`This block overlaps:\n${names}\n\nKeep both blocks in the planner?`)) throw error;
    return api(`${path}${path.includes("?") ? "&" : "?"}allow_conflict=true`, options, token);
  }
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

function plannerInstant(value, timeZone) {
  try { return profileLocalTimeToISO(value, timeZone); }
  catch (error) {
    if (!(error instanceof AmbiguousProfileTimeError)) throw error;
    const offsets = error.candidates.map(candidate => candidate.offset).join(" or ");
    const chosen = window.prompt(`${error.message}\nEnter one offset exactly: ${offsets}`);
    if (!chosen) throw error;
    return profileLocalTimeToISO(value, timeZone, chosen.trim().toUpperCase());
  }
}


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
  const [mode, setMode] = useState("signin");
  const [email, setEmail] = useState("");
  const [identifier, setIdentifier] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [code, setCode] = useState("");
  const [setupToken, setSetupToken] = useState("");
  const [setupName, setSetupName] = useState("");
  const [setupProvider, setSetupProvider] = useState("email");
  const [recoverySession, setRecoverySession] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const googleClientId = import.meta.env.VITE_GOOGLE_CLIENT_ID;

  useEffect(() => {
    if (!googleClientId) return undefined;
    let attempts = 0;
    let timer;
    const renderButton = () => {
      if (!window.google?.accounts?.id) return false;
      const element = document.getElementById("google-signin-button");
      if (!element) return false;
      window.google.accounts.id.initialize({client_id: googleClientId, callback: handleGoogleCredential});
      element.innerHTML = "";
      window.google.accounts.id.renderButton(element, {theme:"outline", size:"large", width:326, text:"continue_with", shape:"rectangular"});
      return true;
    };
    if (renderButton()) return undefined;
    timer = window.setInterval(() => {
      attempts += 1;
      if (renderButton() || attempts >= 50) window.clearInterval(timer);
    }, 100);
    return () => window.clearInterval(timer);
  }, [googleClientId, mode]);

  async function handleGoogleCredential(response) {
    setBusy(true);
    setError("");
    try {
      const data = await api("/auth/google", {method:"POST", body:JSON.stringify({credential:response.credential})});
      if (data.requires_setup) {
        setSetupToken(data.setup_token);
        setEmail(data.email || "");
        setSetupName(data.name || "");
        setSetupProvider("google");
        setUsername("");
        setPassword("");
        setConfirmPassword("");
        setMode("setup");
      } else {
        localStorage.setItem("nexus_token", data.access_token);
        onLogin(data.access_token);
      }
    } catch (err) {
      setError(err.message || "Google sign-in failed. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  async function resendVerificationCode() {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api("/auth/email/start", {
        method: "POST",
        body: JSON.stringify({ email: email.trim() }),
      });
      setCode("");
      setNotice("A new code was requested. Check your inbox and Spam folder. Only the newest code will work.");
    } catch (err) {
      setError(err.message || "Could not resend the code. Please try again later.");
    } finally {
      setBusy(false);
    }
  }

  async function continueAfterRecovery() {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const data = await api("/auth/password-reset/continue", {
        method:"POST", body:JSON.stringify({email:email.trim(), recovery_session:recoverySession})
      });
      localStorage.setItem("nexus_token", data.access_token);
      onLogin(data.access_token);
    } catch (err) {
      setError(err.message || "Your recovery session expired. Request a new code.");
    } finally {
      setBusy(false);
    }
  }

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      if (mode === "signup") {
        await api("/auth/email/start", {method:"POST", body:JSON.stringify({email:email.trim()})});
        setCode("");
        setNotice("If the address can be used for authentication, a verification email has been sent. Check your inbox and Spam folder.");
        setMode("verify");
      } else if (mode === "verify") {
        const data = await api("/auth/email/verify", {method:"POST", body:JSON.stringify({email:email.trim(), code:code.trim().toUpperCase()})});
        if (data.access_token) {
          localStorage.setItem("nexus_token", data.access_token);
          onLogin(data.access_token);
        } else {
          setSetupToken(data.setup_token);
          setSetupName(data.name || "");
          setSetupProvider("email");
          setMode("setup");
        }
      } else if (mode === "setup") {
        if (setupProvider !== "google" && password.length < 8) throw new Error("Password must contain at least 8 characters.");
        if (password && password !== confirmPassword) throw new Error("Passwords do not match.");
        if (setupProvider !== "google" && !password) throw new Error("A password is required.");
        const data = await api("/auth/setup", {
          method:"POST",
          body:JSON.stringify({setup_token:setupToken, username:username.trim(), ...(password ? {password} : {})})
        });
        localStorage.setItem("nexus_token", data.access_token);
        onLogin(data.access_token);
      } else if (mode === "forgot") {
        await api("/auth/password-reset/start", {method:"POST", body:JSON.stringify({email:email.trim()})});
        setCode("");
        setMode("reset");
      } else if (mode === "reset") {
        const data = await api("/auth/password-reset/verify", {method:"POST", body:JSON.stringify({email:email.trim(), reset_token:code.trim().toUpperCase()})});
        setRecoverySession(data.recovery_session);
        setCode("");
        setMode("recovery-choice");
      } else if (mode === "reset-password") {
        if (password.length < 8) throw new Error("Password must contain at least 8 characters.");
        if (password !== confirmPassword) throw new Error("Passwords do not match.");
        const data = await api("/auth/password-reset/complete", {
          method:"POST",
          body:JSON.stringify({email:email.trim(), recovery_session:recoverySession, password})
        });
        localStorage.setItem("nexus_token", data.access_token);
        onLogin(data.access_token);
      } else {
        const key = identifier.includes("@") ? "email" : "username";
        const normalizedIdentifier = key === "email" ? identifier.trim().toLowerCase() : identifier.trim();
        const data = await api("/auth/login", {method:"POST", body:JSON.stringify({[key]:normalizedIdentifier, password})});
        localStorage.setItem("nexus_token", data.access_token);
        onLogin(data.access_token);
      }
    } catch (err) {
      setError(err.message || "Authentication failed. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  function switchMode(next) {
    setError("");
    setNotice("");
    setCode("");
    setPassword("");
    setConfirmPassword("");
    setSetupToken("");
    setRecoverySession("");
    setMode(next);
  }

  const titles = {
    signin:["Welcome back.","Sign in to your NEXUS account."],
    signup:["Create your operating account.","Start with your email. We will verify it before account setup."],
    verify:["Check your email.","Enter the 6-character verification code sent to " + email + "."],
    setup:["Finish your NEXUS account.", setupProvider === "google" ? "Your Google identity is verified. Choose a NEXUS username; password is optional." : "Your email is verified. Choose your username and password."],
    forgot:["Recover your account.","Enter your registered email to request a recovery code."],
    reset:["Verify account ownership.","Enter the recovery code sent to " + email + "."],
    "recovery-choice":["Email verified.","Choose whether to change your password or continue without changing it."],
    "reset-password":["Create a new password.","Choose a replacement password."],
  };
  const [title, subtitle] = titles[mode];

  return <main className="login-shell">
    <section className="login-card">
      <div className="brand-mark">N</div>
      <p className="eyebrow">PERSONAL OPERATING SYSTEM</p>
      <h1>NEXUS</h1>
      <p className="muted">{title}</p>
      {(mode === "signin" || mode === "signup") && <>
        {googleClientId ? <div id="google-signin-button" className="google-auth-button" aria-label="Continue with Google" /> : <button type="button" className="google-fallback-button" onClick={() => setError("Google sign-in is not configured yet. Add VITE_GOOGLE_CLIENT_ID in Vercel and GOOGLE_CLIENT_ID in Render.")}>Continue with Google</button>}
        <div className="auth-divider"><span>or</span></div>
      </>}
      {notice && <div className="notice" role="status">{notice}</div>}
      {mode !== "recovery-choice" && <form onSubmit={submit}>
        {mode === "signin" && <>
          <label>Username or email<input autoComplete="username" value={identifier} onChange={e=>setIdentifier(e.target.value)} required /></label>
          <label>Password<input type="password" autoComplete="current-password" value={password} onChange={e=>setPassword(e.target.value)} minLength={8} maxLength={128} required /></label>
        </>}
        {mode === "signup" && <label>Email<input type="email" autoComplete="email" value={email} onChange={e=>setEmail(e.target.value)} required maxLength={255}/></label>}
        {mode === "verify" && <>
          <label>Verification code<input value={code} onChange={e=>setCode(e.target.value.toUpperCase().replace(/\s/g, ""))} autoCapitalize="characters" autoComplete="one-time-code" inputMode="text" minLength={6} maxLength={10} required /></label>
          <p className="muted small auth-help">Use the newest 6-character code. Codes expire after 15 minutes; check Spam if it is not in your inbox.</p>
        </>}
        {mode === "setup" && <>
          <label>Verified email<input type="email" value={email} disabled /></label>
          <label>Username<input autoComplete="username" value={username} onChange={e=>setUsername(e.target.value)} minLength={3} maxLength={32} required /></label>
          {setupProvider !== "google" && <>
            <label>Password<input type="password" autoComplete="new-password" value={password} onChange={e=>setPassword(e.target.value)} minLength={8} maxLength={128} required /></label>
            <label>Confirm password<input type="password" autoComplete="new-password" value={confirmPassword} onChange={e=>setConfirmPassword(e.target.value)} minLength={8} maxLength={128} required /></label>
          </>}
          {setupProvider === "google" && <>
            <label>Set a NEXUS password (optional)<input type="password" autoComplete="new-password" value={password} onChange={e=>setPassword(e.target.value)} minLength={password ? 8 : undefined} maxLength={128} /></label>
            {password && <label>Confirm password<input type="password" autoComplete="new-password" value={confirmPassword} onChange={e=>setConfirmPassword(e.target.value)} minLength={8} maxLength={128} required /></label>}
          </>}
          {setupName && <p className="muted small">Google profile: {setupName}</p>}
        </>}
        {mode === "forgot" && <label>Email<input type="email" autoComplete="email" value={email} onChange={e=>setEmail(e.target.value)} required maxLength={255}/></label>}
        {mode === "reset" && <label>Recovery code<input value={code} onChange={e=>setCode(e.target.value)} autoCapitalize="characters" inputMode="text" minLength={6} maxLength={10} required /></label>}
        {mode === "reset-password" && <>
          <label>New password<input type="password" autoComplete="new-password" value={password} onChange={e=>setPassword(e.target.value)} minLength={8} maxLength={128} required /></label>
          <label>Confirm new password<input type="password" autoComplete="new-password" value={confirmPassword} onChange={e=>setConfirmPassword(e.target.value)} minLength={8} maxLength={128} required /></label>
        </>}
        {error && <div className="error" role="alert">{error}</div>}
        <button className="primary full" disabled={busy}>
          {busy ? "Working…" : mode==="signin" ? "Enter NEXUS" : mode==="signup" ? "Send verification code" : mode==="verify" ? "Verify email" : mode==="setup" ? "Create NEXUS account" : mode==="forgot" ? "Send recovery code" : mode==="reset" ? "Verify recovery code" : mode==="reset-password" ? "Change password and continue" : "Continue"}
        </button>
      </form>}
      {mode === "recovery-choice" && <div className="form-grid">
        <button className="primary full" type="button" disabled={busy} onClick={()=>{setError("");setPassword("");setConfirmPassword("");setMode("reset-password");}}>Change password</button>
        <button className="ghost full" type="button" disabled={busy} onClick={continueAfterRecovery}>Continue without changing password</button>
        {error && <div className="error" role="alert">{error}</div>}
      </div>}
      {mode === "signin" && <div className="auth-links">
        <button className="auth-switch" type="button" onClick={()=>switchMode("forgot")}>Forgot password?</button>
        <button className="auth-switch" type="button" onClick={()=>switchMode("signup")}>New to NEXUS? Create an account</button>
      </div>}
      {mode === "signup" && <button className="auth-switch" type="button" onClick={()=>switchMode("signin")}>Already have an account? Sign in</button>}
      {mode === "verify" && <button className="auth-switch" type="button" disabled={busy} onClick={resendVerificationCode}>{busy ? "Working…" : "Didn't receive a code? Resend email"}</button>}
      {(mode==="verify" || mode==="setup" || mode==="forgot" || mode==="reset" || mode==="recovery-choice" || mode==="reset-password") && <button className="auth-switch" type="button" onClick={()=>switchMode("signin")}>Back to sign in</button>}
      {mode !== "signin" && mode !== "signup" && <p className="muted small">{subtitle}</p>}
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
  if (profile && !profile.onboarding_completed) {
    return <ProfileOnboarding token={token} onComplete={setProfile} initialProfile={profile} />;
  }
  if (!profile || !isValidTimeZone(profile.timezone)) {
    return <main className="auth-shell"><section className="auth-card"><h1>Profile timezone unavailable</h1><p className="muted">Set a valid IANA timezone in your NEXUS profile before planning activities.</p></section></main>;
  }

  return <Dashboard token={token} profile={profile} onLogout={logout} />;
}

function Dashboard({ token, profile, onLogout }) {
  const [view, setView] = useState("Overview");
  const [data, setData] = useState({ analytics: null, schedule: [], current: null, targets: [], habits: [], habitStats: [], history: [], activities: [], routines: [], diary: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [timerTitle, setTimerTitle] = useState("");
  const emptyActivityForm = { metric_value: "", topic: "", pattern: "", book: "", chapter: "", practice_type: "", workstream: "", milestone: "", accuracy: "", attempted: "", mistakes: "", words_learned: "", key_concepts: "", subject: "", difficulty: "", notes: "" };
  const [activityForm, setActivityForm] = useState(emptyActivityForm);
  const [now, setNow] = useState(Date.now());
  const [timerSnapshotAt, setTimerSnapshotAt] = useState(Date.now());
  const timezone = profile.timezone;
  const [scheduleDate, setScheduleDate] = useState(() => profileDate(new Date(), timezone));

  const date = profileDate(new Date(), timezone);
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
      setTimerSnapshotAt(Date.now());
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
      setView("Activity");
    } catch (err) { setError(err.message); }
  }

  async function pauseTimer() {
    if (!data.current) return;
    try { await api(`/time-sessions/${data.current.id}/pause`, { method: "POST" }, token); await load(); }
    catch (err) { setError(err.message); }
  }

  async function resumeTimer() {
    if (!data.current) return;
    try { await api(`/time-sessions/${data.current.id}/resume`, { method: "POST" }, token); await load(); }
    catch (err) { setError(err.message); }
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

  async function loadScheduleRange(startDate, endDate) {
    const schedule = await api(`/schedule?start_date=${startDate}&end_date=${endDate}`, {}, token);
    setData(prev => ({ ...prev, schedule }));
  }

  async function updateSchedule(item, patch, refreshDate = scheduleDate) {
    try { await requestScheduleChange(`/schedule/${item.id}`, { method:"PATCH", body:JSON.stringify(patch) }, token, timezone); await loadScheduleFor(refreshDate); }
    catch (err) { setError(err.message); }
  }

  async function deleteSchedule(item, refreshDate = scheduleDate) {
    if (!window.confirm(`Remove “${item.title}” from the active planner? Execution history will be preserved.`)) return;
    try { await api(`/schedule/${item.id}`, { method:"DELETE" }, token); await loadScheduleFor(refreshDate); }
    catch (err) { setError(err.message); }
  }

  async function createRoutine(form) {
    await api("/routines", { method: "POST", body: JSON.stringify({
      title: form.title, notes: form.notes || null, weekdays: form.weekdays.map(Number),
      start_time: form.start_time, end_time: form.end_time,
      habit_id: form.habit_id || null, target_id: form.target_id || null,
      priority: Number(form.priority), active: true
    }) }, token, timezone);
    await load();
  }

  async function generateRoutine(targetDate) {
    await api("/routines/generate/" + targetDate, { method: "POST" }, token);
    await loadScheduleFor(targetDate);
    setView("Schedule");
    setScheduleDate(targetDate);
  }

  async function createSchedule(form) {
    try { await requestScheduleChange("/schedule", { method: "POST", body: JSON.stringify({
      title: form.title, notes: form.notes || null, scheduled_date: form.scheduled_date,
      start_at: plannerInstant(form.start_at, timezone), end_at: plannerInstant(form.end_at, timezone),
      priority: Number(form.priority), target_id: form.target_id || null, ambition_goal_id: form.ambition_goal_id || null, status: "planned"
    }) }, token);
      await loadScheduleFor(form.scheduled_date);
      return true;
    } catch (err) { setError(err.message); return false; }
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

  const actualRunning = data.current ? Math.max(0, (data.current.elapsed_seconds || 0) + (data.current.status === "running" ? Math.floor((now - timerSnapshotAt) / 1000) : 0)) : 0;
  const totals = data.analytics?.totals || {};
  const targets = data.targets.map(t => ({
    ...t, progress_percent: t.target_value ? Math.min(100, t.current_value / t.target_value * 100) : 0
  }));
  const greeting = useMemo(() => {
    const h = new Date().getHours();
    return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
  }, []);

  if (loading) return <div className="loading">Loading NEXUS<span>•</span><span>•</span><span>•</span></div>;

  const nav = ["Overview", "Ambitions", "Tasks", "Routine", "Schedule", "Habits", "Targets", "History", "Activity", "Analytics", "Diary"];

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

      {view === "Overview" && <Overview timezone={timezone} data={data} targets={targets} actualRunning={actualRunning} timerTitle={timerTitle} setTimerTitle={setTimerTitle} startTimer={startTimer} pauseTimer={pauseTimer} resumeTimer={resumeTimer} stopTimer={stopTimer} activityForm={activityForm} setActivityForm={setActivityForm} markSchedule={markSchedule} onTargetChange={updateScheduleTarget} totals={totals} />}
      {view === "Ambitions" && <Ambitions token={token} />}
      {view === "Tasks" && <TasksView token={token} />}
      {view === "Routine" && <RoutineView date={scheduleDate} routines={data.routines} habits={data.habits} targets={data.targets} onCreate={createRoutine} onGenerate={generateRoutine} />}
      {view === "Schedule" && <PlannerView token={token} timezone={timezone} date={scheduleDate} schedule={data.schedule} targets={data.targets} onDateChange={async (next) => { setScheduleDate(next); await loadScheduleFor(next); }} onRangeChange={loadScheduleRange} onCreate={createSchedule} onUpdate={(item, patch) => updateSchedule(item, patch, scheduleDate)} onDelete={item => deleteSchedule(item, scheduleDate)} onStart={startSchedule} />}
      {view === "Habits" && <HabitsView habits={data.habits} habitStats={data.habitStats} onCreate={createHabit} />}
      {view === "Targets" && <TargetsView targets={targets} onCreate={createTarget} onUpdate={updateTarget} onDelete={deleteTarget} />}
      {view === "History" && <HistoryView history={data.history} activities={data.activities} targets={data.targets} habits={data.habits} onReview={saveActivity} />}
      {view === "Activity" && <ActivityReview token={token} targets={targets} />}
      {view === "Analytics" && <AnalyticsView token={token} timeZone={timezone} />}
      {view === "Diary" && <DiaryView date={date} existing={data.diary[0]} onSave={createDiary} />}
    </main>
  </div>;
}

function TasksView({ token }) {
  const [tasks, setTasks] = useState([]);
  const [goals, setGoals] = useState([]);
  const [projects, setProjects] = useState([]);
  const [filters, setFilters] = useState({ status_filter:"", priority:"", project_id:"", ambition_goal_id:"", due_from:"", due_to:"" });
  const [form, setForm] = useState({ title:"", description:"", priority:3, due_at:"", project_id:"", ambition_goal_id:"" });
  const [error, setError] = useState("");
  const load = async () => {
    try {
      const query = new URLSearchParams(Object.entries(filters).filter(([,v]) => v !== "")).toString();
      const [rows, ambitions, projectRows] = await Promise.all([
        api(`/tasks${query ? `?${query}` : ""}`, {}, token), api("/ambitions?include_archived=true", {}, token), api("/projects", {}, token)
      ]);
      const nested = await Promise.all(ambitions.map(a => api(`/ambitions/${a.id}/goals`, {}, token)));
      setTasks(rows); setGoals(nested.flat()); setProjects(projectRows);
    } catch (e) { setError(e.message); }
  };
  useEffect(() => { load(); }, [token, JSON.stringify(filters)]);
  async function create(e) {
    e.preventDefault(); setError("");
    try { await api("/tasks", { method:"POST", body:JSON.stringify({ ...form, priority:Number(form.priority), due_at:form.due_at ? new Date(form.due_at).toISOString() : null, project_id:form.project_id || null, ambition_goal_id:form.ambition_goal_id || null }) }, token); setForm({ title:"", description:"", priority:3, due_at:"", project_id:"", ambition_goal_id:"" }); await load(); }
    catch (err) { setError(err.message); }
  }
  async function update(task, patch) {
    try { await api(`/tasks/${task.id}`, { method:"PATCH", body:JSON.stringify(patch) }, token); await load(); }
    catch (err) { setError(err.message); }
  }
  async function remove(task) {
    if (!window.confirm(`Archive task “${task.title}”? Its history will be preserved.`)) return;
    try { await api(`/tasks/${task.id}`, { method:"DELETE" }, token); await load(); } catch (err) { setError(err.message); }
  }
  return <section className="two-col">
    <div className="panel"><PanelTitle eyebrow="TASK MANAGEMENT" title="Create task" />{error && <div className="error">{error}</div>}
      <form className="form-grid" onSubmit={create}>
        <label>Title<input value={form.title} onChange={e=>setForm({...form,title:e.target.value})} required maxLength={255}/></label>
        <label>Description<textarea value={form.description} onChange={e=>setForm({...form,description:e.target.value})}/></label>
        <label>Priority<select value={form.priority} onChange={e=>setForm({...form,priority:e.target.value})}>{[1,2,3,4,5].map(n=><option key={n}>{n}</option>)}</select></label>
        <label>Due date<input type="datetime-local" value={form.due_at} onChange={e=>setForm({...form,due_at:e.target.value})}/></label>
        <label>Project<select value={form.project_id} onChange={e=>setForm({...form,project_id:e.target.value})}><option value="">None</option>{projects.map(p=><option value={p.id} key={p.id}>{p.name}</option>)}</select></label>
        <label>Long-term goal<select value={form.ambition_goal_id} onChange={e=>setForm({...form,ambition_goal_id:e.target.value})}><option value="">None</option>{goals.map(g=><option value={g.id} key={g.id}>{g.title}</option>)}</select></label>
        <button className="primary">Create task</button>
      </form>
    </div>
    <div className="panel"><PanelTitle eyebrow="YOUR WORK" title="Tasks" />
      <div className="form-grid task-filters">
        <label>Status<select value={filters.status_filter} onChange={e=>setFilters({...filters,status_filter:e.target.value})}><option value="">All</option>{["planned","in_progress","completed","blocked","cancelled"].map(s=><option key={s}>{s}</option>)}</select></label>
        <label>Priority<select value={filters.priority} onChange={e=>setFilters({...filters,priority:e.target.value})}><option value="">All</option>{[1,2,3,4,5].map(n=><option key={n}>{n}</option>)}</select></label><label>Project<select value={filters.project_id} onChange={e=>setFilters({...filters,project_id:e.target.value})}><option value="">All</option>{projects.map(p=><option value={p.id} key={p.id}>{p.name}</option>)}</select></label><label>Long-term goal<select value={filters.ambition_goal_id} onChange={e=>setFilters({...filters,ambition_goal_id:e.target.value})}><option value="">All</option>{goals.map(g=><option value={g.id} key={g.id}>{g.title}</option>)}</select></label>
        <label>Due from<input type="date" value={filters.due_from} onChange={e=>setFilters({...filters,due_from:e.target.value})}/></label>
        <label>Due to<input type="date" value={filters.due_to} onChange={e=>setFilters({...filters,due_to:e.target.value})}/></label>
      </div>
      {tasks.length ? <div className="item-list">{tasks.map(task=><TaskRow key={task.id} token={token} task={task} projects={projects} goals={goals} onUpdate={patch=>update(task,patch)} onRemove={()=>remove(task)} />)}</div> : <Empty text="No tasks match these filters." />}
    </div>
  </section>;
}

function TaskRow({ token, task, projects, goals, onUpdate, onRemove }) {
  const [editing, setEditing] = useState(false);
  const [history, setHistory] = useState(null);
  const [form, setForm] = useState({ title:task.title, description:task.description||"", priority:task.priority, due_at:task.due_at?localDateTime(new Date(task.due_at)):"", project_id:task.project_id||"", ambition_goal_id:task.ambition_goal_id||"" });
  const save = async e => { e.preventDefault(); await onUpdate({ title:form.title, description:form.description||null, priority:Number(form.priority), due_at:form.due_at?new Date(form.due_at).toISOString():null, project_id:form.project_id||null, ambition_goal_id:form.ambition_goal_id||null }); setEditing(false); };
  if (editing) return <form className="list-item form-grid" onSubmit={save}><label>Title<input required value={form.title} onChange={e=>setForm({...form,title:e.target.value})}/></label><label>Description<textarea value={form.description} onChange={e=>setForm({...form,description:e.target.value})}/></label><label>Priority<select value={form.priority} onChange={e=>setForm({...form,priority:e.target.value})}>{[1,2,3,4,5].map(n=><option key={n}>{n}</option>)}</select></label><label>Due date<input type="datetime-local" value={form.due_at} onChange={e=>setForm({...form,due_at:e.target.value})}/></label><label>Project<select value={form.project_id} onChange={e=>setForm({...form,project_id:e.target.value})}><option value="">None</option>{projects.map(p=><option value={p.id} key={p.id}>{p.name}</option>)}</select></label><label>Long-term goal<select value={form.ambition_goal_id} onChange={e=>setForm({...form,ambition_goal_id:e.target.value})}><option value="">None</option>{goals.map(g=><option value={g.id} key={g.id}>{g.title}</option>)}</select></label><div className="row-actions"><button className="primary">Save</button><button type="button" onClick={()=>setEditing(false)}>Cancel</button></div></form>;
  return <div className="list-item"><div><strong>{task.title}</strong><span>Priority {task.priority}{task.due_at ? ` · Due ${new Date(task.due_at).toLocaleString()}` : " · No deadline"}{task.project_id ? ` · ${projects.find(p=>p.id===task.project_id)?.name || "Project"}` : ""}{task.ambition_goal_id ? ` · Goal: ${goals.find(g=>g.id===task.ambition_goal_id)?.title || "Linked"}` : ""}</span>{history && <span>{history.map(e=>`${e.previous_status||"created"} → ${e.new_status} · ${new Date(e.created_at).toLocaleString()}`).join(" | ")}</span>}</div><div className="row-actions"><select aria-label={`Status for ${task.title}`} value={task.status} onChange={e=>onUpdate({status:e.target.value})}>{["planned","in_progress","completed","blocked","cancelled"].map(s=><option key={s}>{s}</option>)}</select><button onClick={()=>setEditing(true)}>Edit</button><button onClick={async()=>{if(history===null)setHistory(await api(`/tasks/${task.id}/history`,{},token));else setHistory(null);}}>{history===null?"History":"Hide history"}</button><button className="danger-text" onClick={onRemove}>Archive</button></div></div>;
}

function Overview({ data, targets, actualRunning, timerTitle, setTimerTitle, startTimer, pauseTimer, resumeTimer, stopTimer, activityForm, setActivityForm, markSchedule, onTargetChange, totals, timezone }) {
  return <>
    <section className="hero-grid">
      <div className={`timer-card ${data.current?.status === "running" ? "running" : ""}`}>
        <div className="card-top"><span className="eyebrow">FOCUS TIMER</span><span className="live-dot">{data.current?.status?.toUpperCase() || "READY"}</span></div>
        <div className="timer-value">{formatSeconds(data.current ? actualRunning : 0)}</div>
        {data.current ? <><div className="timer-title">{data.current.title}</div><p className="muted small">Paused intervals are excluded. Review the completed session in Activity.</p><div className="row-actions">{data.current.status === "running" ? <button onClick={pauseTimer}>Pause</button> : <button className="primary" onClick={resumeTimer}>Resume</button>}<button className="danger" onClick={stopTimer}>Stop session</button></div></>
          : <div className="timer-start"><input placeholder="What are you working on?" value={timerTitle} onChange={e => setTimerTitle(e.target.value)} onKeyDown={e => e.key === "Enter" && startTimer()} /><button className="primary" onClick={startTimer}>Start</button></div>}
      </div>
      <div className="stat-card"><span className="eyebrow">FOCUSED TODAY</span><strong>{formatSeconds(totals.actual_seconds)}</strong><p>Actual tracked time</p></div>
      <div className="stat-card"><span className="eyebrow">PLANNED</span><strong>{formatSeconds(totals.planned_seconds)}</strong><p>{totals.planned_items || 0} scheduled blocks</p></div>
      <div className="stat-card"><span className="eyebrow">EXECUTION</span><strong>{totals.schedule_completion_rate || 0}%</strong><p>{totals.completed_items || 0} of {totals.planned_items || 0} completed</p></div>
    </section>
    <section className="content-grid">
      <div className="panel schedule-panel"><div className="panel-head"><div><span className="eyebrow">TODAY</span><h3>Execution schedule</h3></div><span className="count">{data.schedule.length}</span></div>
        {data.schedule.length === 0 ? <Empty text="Nothing scheduled yet. Use Schedule to plan your day." /> : <div className="schedule-list">{data.schedule.map(item => <div className={`schedule-row ${item.status}`} key={item.id}>
          <div className="time">{profileClock(item.start_at,timezone)}<small>{profileClock(item.end_at,timezone)}</small></div>
          <div className="schedule-info"><strong>{item.title}</strong><span>{item.notes || "Focus block"}</span><select className="schedule-target" value={item.target_id || ""} onChange={e => onTargetChange(item, e.target.value)}><option value="">No target</option>{targets.map(t => <option key={t.id} value={t.id}>{t.title} · {METRIC_LABELS[t.metric_type] || t.metric_type}</option>)}</select></div>
          <div className="row-actions">{(item.status === "planned" || item.status === "partial") && <><button onClick={() => markSchedule(item, "completed")}>Done</button>{item.status === "planned" && <button onClick={() => markSchedule(item, "skipped")}>Skip</button>}</>}</div>
        </div>)}</div>}
      </div>
      <div className="panel"><div className="panel-head"><div><span className="eyebrow">OCTOBER</span><h3>Targets</h3></div></div>
        {targets.length === 0 ? <Empty text="No monthly targets yet." /> : targets.slice(0, 4).map(t => <TargetCard key={t.id} t={t} />)}
      </div>
    </section>
    <section className="panel metrics"><div className="panel-head"><div><span className="eyebrow">TODAY</span><h3>Operating pulse</h3></div></div>
      <div className="metric-grid"><Metric label="Manual activity records" value={totals.activity_count || 0} /><Metric label="Confirmed sessions" value={totals.session_count || 0} /><Metric label="Diary" value={totals.diary_days || 0} /><Metric label="Skipped" value={totals.skipped_items || 0} /></div>
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

function PlannerView({ token, timezone, date, schedule, targets, onDateChange, onRangeChange, onCreate, onUpdate, onDelete, onStart }) {
  const [mode, setMode] = useState("day");
  const [editing, setEditing] = useState(null);
  const [editForm, setEditForm] = useState({});
  const [form, setForm] = useState({ title:"", notes:"", scheduled_date:date, start_at:`${date}T18:00`, end_at:`${date}T19:00`, priority:3, target_id:"", ambition_goal_id:"" });
  const [goals, setGoals] = useState([]);
  const [execution, setExecution] = useState({ items: [], totals: null });
  const [plannerError, setPlannerError] = useState("");
  useEffect(()=>setForm(v=>({...v,scheduled_date:date,start_at:`${date}T18:00`,end_at:`${date}T19:00`})),[date]);
  const weekStart=(()=>{const [year,month,day]=date.split("-").map(Number);const d=new Date(Date.UTC(year,month-1,day));return addCalendarDays(date,-((d.getUTCDay()+6)%7));})();
  const weekEnd=addCalendarDays(weekStart,6);
  useEffect(()=>{if(mode==="week")onRangeChange(weekStart,weekEnd);else onDateChange(date);},[mode,date]);
  useEffect(()=>{let live=true;api("/ambitions?include_archived=false",{},token).then(async rows=>{const all=await Promise.all(rows.map(a=>api(`/ambitions/${a.id}/goals`,{},token)));if(live)setGoals(all.flat());}).catch(()=>{});return()=>{live=false;};},[token]);
  useEffect(()=>{const start=mode==="week"?weekStart:date,end=mode==="week"?weekEnd:date;api(`/schedule/execution?start_date=${start}&end_date=${end}`,{},token).then(setExecution).catch(()=>setExecution({items:[],totals:null}));},[mode,date,token]);
  const shift=delta=>onDateChange(addCalendarDays(mode==="week"?weekStart:date,delta*(mode==="week"?7:1)));
  const updateBlock=async(item,patch)=>{await onUpdate(item,patch);if(mode==="week")await onRangeChange(weekStart,weekEnd);};
  const deleteBlock=async item=>{await onDelete(item);if(mode==="week")await onRangeChange(weekStart,weekEnd);};
  const days=Array.from({length:7},(_,i)=>{const key=addCalendarDays(weekStart,i);const d=new Date(`${key}T12:00:00Z`);return {key,label:new Intl.DateTimeFormat(undefined,{timeZone:"UTC",weekday:"long",month:"short",day:"numeric"}).format(d),items:schedule.filter(item=>item.scheduled_date===key)}});
  const create=async e=>{e.preventDefault();setPlannerError("");const result=await onCreate(form);if(result!==false)setForm(v=>({...v,title:"",notes:"",target_id:"",ambition_goal_id:""}));};
  const startEdit=item=>{setPlannerError("");setEditing(item.id);setEditForm({title:item.title,notes:item.notes||"",scheduled_date:item.scheduled_date,start_at:profileDateTimeInput(item.start_at,timezone),end_at:profileDateTimeInput(item.end_at,timezone),target_id:item.target_id||"",ambition_goal_id:item.ambition_goal_id||"",priority:item.priority});};
  const save=async item=>{try{setPlannerError("");await onUpdate(item,{title:editForm.title,notes:editForm.notes||null,scheduled_date:editForm.scheduled_date,start_at:plannerInstant(editForm.start_at,timezone),end_at:plannerInstant(editForm.end_at,timezone),target_id:editForm.target_id||null,ambition_goal_id:editForm.ambition_goal_id||null,priority:Number(editForm.priority)});setEditing(null);if(editForm.scheduled_date!==date)onDateChange(editForm.scheduled_date);else if(mode==="week")await onRangeChange(weekStart,weekEnd);}catch(error){setPlannerError(error.message);}};
  const card=(item)=> <div className={`schedule-row ${item.status}`} key={item.id}>
    {editing===item.id ? <div className="form-grid schedule-edit"><label>Title<input value={editForm.title} onChange={e=>setEditForm({...editForm,title:e.target.value})}/></label><label>Date<input type="date" value={editForm.scheduled_date} onChange={e=>setEditForm({...editForm,scheduled_date:e.target.value})}/></label><label>Start<input type="datetime-local" value={editForm.start_at} onChange={e=>setEditForm({...editForm,start_at:e.target.value})}/></label><label>End<input type="datetime-local" value={editForm.end_at} onChange={e=>setEditForm({...editForm,end_at:e.target.value})}/></label><label>Notes<textarea value={editForm.notes} onChange={e=>setEditForm({...editForm,notes:e.target.value})}/></label><label>Target<select value={editForm.target_id} onChange={e=>setEditForm({...editForm,target_id:e.target.value})}><option value="">None</option>{targets.map(t=><option key={t.id} value={t.id}>{t.title}</option>)}</select></label><label>Long-term goal<select value={editForm.ambition_goal_id} onChange={e=>setEditForm({...editForm,ambition_goal_id:e.target.value})}><option value="">None</option>{goals.map(g=><option key={g.id} value={g.id}>{g.title}</option>)}</select></label><label>Priority<select value={editForm.priority} onChange={e=>setEditForm({...editForm,priority:e.target.value})}>{[1,2,3,4,5].map(n=><option key={n}>{n}</option>)}</select></label><div className="row-actions"><button className="primary" onClick={()=>save(item)}>Save</button><button onClick={()=>setEditing(null)}>Cancel</button></div></div> : <><div className="time">{profileClock(item.start_at,timezone)}<small>{profileClock(item.end_at,timezone)}</small></div><div className="schedule-info"><strong>{item.title}</strong><span>{item.status}{item.target_id?" · Target linked":""}{item.routine_template_id&&<span>Routine occurrence</span>}</span><span>Confirmed actual {formatSeconds(execution.items.find(x=>x.schedule_item.id===item.id)?.confirmed_actual_seconds||0)} · Ambiguous {formatSeconds(execution.items.find(x=>x.schedule_item.id===item.id)?.ambiguous_actual_seconds||0)} · Outside planned {formatSeconds(execution.items.find(x=>x.schedule_item.id===item.id)?.outside_planned_seconds||0)}</span></div><div className="row-actions">{(item.status==="planned"||item.status==="partial")&&<><button onClick={()=>onStart(item)}>Start</button><button onClick={()=>updateBlock(item,{status:"completed"})}>Done</button><button onClick={()=>updateBlock(item,{status:"skipped"})}>Skip</button></>}<button onClick={()=>startEdit(item)}>Edit/Move</button><button className="danger-text" onClick={()=>deleteBlock(item)}>Delete</button></div></>}
  </div>;
  return <section className="two-col"><div className="panel">{plannerError&&<div className="error banner">{plannerError}</div>}<PanelTitle eyebrow="PLAN" title="Add schedule block"/><form className="form-grid" onSubmit={create}><label>Title<input required value={form.title} onChange={e=>setForm({...form,title:e.target.value})}/></label><label>Notes<textarea value={form.notes} onChange={e=>setForm({...form,notes:e.target.value})}/></label><label>Date<input type="date" value={form.scheduled_date} onChange={e=>setForm({...form,scheduled_date:e.target.value,start_at:`${e.target.value}T18:00`,end_at:`${e.target.value}T19:00`})}/></label><label>Start<input type="datetime-local" value={form.start_at} onChange={e=>setForm({...form,start_at:e.target.value})}/></label><label>End<input type="datetime-local" value={form.end_at} onChange={e=>setForm({...form,end_at:e.target.value})}/></label><label>Target<select value={form.target_id} onChange={e=>setForm({...form,target_id:e.target.value})}><option value="">None</option>{targets.map(t=><option key={t.id} value={t.id}>{t.title}</option>)}</select></label><label>Long-term goal<select value={form.ambition_goal_id} onChange={e=>setForm({...form,ambition_goal_id:e.target.value})}><option value="">None</option>{goals.map(g=><option key={g.id} value={g.id}>{g.title}</option>)}</select></label><label>Priority<select value={form.priority} onChange={e=>setForm({...form,priority:e.target.value})}>{[1,2,3,4,5].map(n=><option key={n}>{n}</option>)}</select></label><button className="primary">Add to schedule</button></form></div>
    <div className="panel"><div className="panel-head"><div><span className="eyebrow">{mode==="week"?`${weekStart} — ${weekEnd}`:date}</span><h3>{mode==="week"?"Weekly timetable":"Daily plan"}</h3><p className="muted small">{mode==="week"?"Planned duration by date; actual duration uses confirmed activity evidence.":new Intl.DateTimeFormat(undefined,{timeZone:"UTC",weekday:"long",month:"short",day:"numeric",year:"numeric"}).format(new Date(`${date}T12:00:00Z`))}</p></div><div className="date-nav"><button type="button" className={mode==="day"?"primary":"ghost"} onClick={()=>setMode("day")}>Day</button><button type="button" className={mode==="week"?"primary":"ghost"} onClick={()=>setMode("week")}>Week</button><button type="button" className="ghost small-btn" onClick={()=>shift(-1)}>←</button><button type="button" className="ghost small-btn" onClick={()=>shift(1)}>→</button></div></div>
      {mode==="day" ? schedule.length? <div className="schedule-list">{schedule.map(card)}</div>:<Empty text="No blocks planned."/> : <><p className="muted small">Confirmed actual across this week: {formatSeconds(execution.totals?.confirmed_actual_seconds || 0)} · {formatSeconds(execution.totals?.ambiguous_actual_seconds || 0)} ambiguous with planned intervals.{execution.totals?.unavailable_legacy_seconds ? ` ${formatSeconds(execution.totals.unavailable_legacy_seconds)} legacy stopwatch time unavailable.` : ""}</p><div className="week-grid">{days.map(day=>{const planned=day.items.filter(x=>x.status!=="cancelled").reduce((s,x)=>s+Math.max(0,(new Date(x.end_at)-new Date(x.start_at))/1000),0);return <article className="week-day" key={day.key}><button className="week-day-title" onClick={()=>{setMode("day");onDateChange(day.key);}}>{day.label}</button><p className="muted small">Planned {formatSeconds(planned)}</p>{day.items.length?day.items.map(card):<span className="muted small">No blocks planned</span>}</article>})}</div></>}
    </div></section>;
}

function ScheduleView({ date, schedule, targets, onDateChange, onRangeChange, onCreate, onUpdate, onDelete, onStart, timezone }) {
  const [mode, setMode] = useState("day");
  const [editingId, setEditingId] = useState(null);
  const [edit, setEdit] = useState({});
  const [form, setForm] = useState({ title: "", notes: "", scheduled_date: date, start_at: `${date}T18:00`, end_at: `${date}T19:00`, priority: 3, target_id: "" });
  useEffect(() => {
    setForm(prev => ({ ...prev, scheduled_date: date, start_at: `${date}T18:00`, end_at: `${date}T19:00` }));
  }, [date]);
  const shiftDate = (days) => {
    onDateChange(addCalendarDays(date, days));
  };
  const dateLabel = new Intl.DateTimeFormat(undefined, { timeZone: "UTC", weekday: "long", month: "short", day: "numeric", year: "numeric" }).format(new Date(`${date}T12:00:00Z`));
  const weekStart = (() => { const [year,month,day]=date.split("-").map(Number); const d=new Date(Date.UTC(year,month-1,day)); return addCalendarDays(date,-((d.getUTCDay()+6)%7)); })();
  const weekEnd = addCalendarDays(weekStart, 6);
  useEffect(() => { if (mode === "week") onRangeChange(weekStart, weekEnd); else onDateChange(date); }, [mode, date]);
  const shift = delta => onDateChange(addCalendarDays(mode === "week" ? weekStart : date, delta * (mode === "week" ? 7 : 1)));
  const startEdit = item => { setEditingId(item.id); setEdit({ title:item.title, notes:item.notes||"", date:item.scheduled_date, start:profileDateTimeInput(item.start_at,timezone), end:profileDateTimeInput(item.end_at,timezone), target_id:item.target_id||"" }); };
  const saveEdit = async item => { await onUpdate(item, { title:edit.title, notes:edit.notes||null, scheduled_date:edit.date, start_at:plannerInstant(edit.start,timezone), end_at:plannerInstant(edit.end,timezone), target_id:edit.target_id||null }); setEditingId(null); };
  const blocks = mode === "week" ? schedule.filter(item=>item.scheduled_date>=weekStart&&item.scheduled_date<=weekEnd) : schedule;
  const days = Array.from({length:7},(_,n)=>{const key=addCalendarDays(weekStart,n);const d=new Date(`${key}T12:00:00Z`);return {key,label:new Intl.DateTimeFormat(undefined,{timeZone:"UTC",weekday:"long",month:"short",day:"numeric"}).format(d),items:blocks.filter(item=>item.scheduled_date===key)}});
  const submit = async e => { e.preventDefault(); await onCreate(form); setForm({ ...form, title: "", notes: "", target_id: "" }); };
  return <section className="two-col"><div className="panel"><PanelTitle eyebrow="PLAN" title="Add schedule block" /><form className="form-grid" onSubmit={submit}>
    <label>Title<input value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} required /></label>
    <label>Notes<textarea value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} /></label>
    <label>Date<input type="date" value={form.scheduled_date} onChange={e => { const d=e.target.value; setForm({ ...form, scheduled_date:d, start_at:`${d}T18:00`, end_at:`${d}T19:00` }); }} required /></label>
    <div className="inline-fields"><label>Start<input type="datetime-local" value={form.start_at} onChange={e => setForm({ ...form, start_at:e.target.value })} required /></label><label>End<input type="datetime-local" value={form.end_at} onChange={e => setForm({ ...form, end_at:e.target.value })} required /></label></div>
    <label>Target<select value={form.target_id} onChange={e => setForm({ ...form, target_id:e.target.value })}><option value="">No target</option>{targets.map(t => <option key={t.id} value={t.id}>{t.title}</option>)}</select></label><label>Priority<select value={form.priority} onChange={e => setForm({ ...form, priority:e.target.value })}><option value="1">1 — Critical</option><option value="2">2 — High</option><option value="3">3 — Normal</option><option value="4">4 — Low</option><option value="5">5 — Lowest</option></select></label>
    <button className="primary">Add to schedule</button>
  </form></div><div className="panel"><div className="panel-head"><div><span className="eyebrow">{date}</span><h3>{date === localDate() ? "Today’s plan" : "Planned execution"}</h3><p className="muted small">{dateLabel}</p></div><div className="date-nav"><button className="ghost small-btn" type="button" onClick={() => shiftDate(-1)}>←</button><button className="ghost small-btn" type="button" onClick={() => shiftDate(1)}>→</button></div></div><div className="schedule-list">{schedule.length ? schedule.map(item => <div className={`schedule-row ${item.status}`} key={item.id}><div className="time">{profileClock(item.start_at,timezone)}<small>{profileClock(item.end_at,timezone)}</small></div><div className="schedule-info"><strong>{item.title}</strong><span>{item.notes || "Focus block"}{item.target_id && " · Target linked"}{item.status === "partial" && " · Partial"}</span></div><div className="row-actions">{(item.status === "planned" || item.status === "partial") && <><button onClick={() => onStart(item)}>Start</button><button onClick={() => onUpdate(item,"completed")}>Done</button>{item.status === "planned" && <button onClick={() => onUpdate(item,"skipped")}>Skip</button>}</>}</div></div>) : <Empty text="No blocks planned." />}</div></div></section>;
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

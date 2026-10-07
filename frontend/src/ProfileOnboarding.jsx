import React, { useState } from "react";

const API = "http://127.0.0.1:8000/api/v1";

async function request(path, options = {}, token) {
  const response = await fetch(API + path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    },
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(data?.detail || `Request failed (${response.status})`);
  }
  return data;
}

const INITIAL_FORM = {
  name: "",
  college: "",
  degree: "B.Tech",
  branch: "",
  year: "",
  semester: "",
  timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Kolkata",
  weekdayStart: "18:00",
  weekdayEnd: "21:00",
  weekendStart: "09:00",
  weekendEnd: "13:00",
  planningStyle: "focused",
};

export default function ProfileOnboarding({ token, onComplete }) {
  const [step, setStep] = useState(1);
  const [form, setForm] = useState(INITIAL_FORM);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  function update(field, value) {
    setForm(current => ({ ...current, [field]: value }));
  }

  function next() {
    setError("");
    if (step === 1) {
      if (!form.name.trim() || !form.college.trim() || !form.branch.trim()) {
        setError("Name, college, and branch are required.");
        return;
      }
      if (!form.year || !form.semester) {
        setError("Select your current year and semester.");
        return;
      }
    }
    setStep(current => Math.min(3, current + 1));
  }

  async function finish() {
    setBusy(true);
    setError("");
    try {
      const profile = await request("/profile", {
        method: "PUT",
        body: JSON.stringify({
          name: form.name.trim(),
          college: form.college.trim(),
          degree: form.degree.trim(),
          branch: form.branch.trim(),
          year: Number(form.year),
          semester: Number(form.semester),
          timezone: form.timezone,
          availability: {
            weekday: { start: form.weekdayStart, end: form.weekdayEnd },
            weekend: { start: form.weekendStart, end: form.weekendEnd },
          },
          preferences: {
            planning_style: form.planningStyle,
          },
          onboarding_completed: true,
        }),
      }, token);
      onComplete(profile);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return <main className="onboarding-shell">
    <section className="onboarding-card">
      <div className="onboarding-brand">
        <div className="brand-mark">N</div>
        <div>
          <p className="eyebrow">NEXUS SETUP</p>
          <strong>Build your operating profile</strong>
        </div>
      </div>

      <div className="onboarding-progress">
        {[1, 2, 3].map(value =>
          <div key={value} className={value <= step ? "progress-step active" : "progress-step"}>
            <span>{value}</span>
            <small>{value === 1 ? "About you" : value === 2 ? "Availability" : "Planning"}</small>
          </div>
        )}
      </div>

      {step === 1 && <div className="onboarding-content">
        <p className="eyebrow">01 · ABOUT YOU</p>
        <h1>Let NEXUS understand your context.</h1>
        <p className="muted">This information is used to make targets, schedules, and future recommendations relevant to you.</p>
        <div className="onboarding-grid">
          <label>Name<input value={form.name} onChange={e => update("name", e.target.value)} placeholder="Your name" /></label>
          <label>College<input value={form.college} onChange={e => update("college", e.target.value)} placeholder="College or university" /></label>
          <label>Degree<input value={form.degree} onChange={e => update("degree", e.target.value)} /></label>
          <label>Branch<input value={form.branch} onChange={e => update("branch", e.target.value)} placeholder="e.g. CSM" /></label>
          <label>Year<select value={form.year} onChange={e => update("year", e.target.value)}><option value="">Select</option>{[1,2,3,4].map(value => <option key={value} value={value}>Year {value}</option>)}</select></label>
          <label>Semester<select value={form.semester} onChange={e => update("semester", e.target.value)}><option value="">Select</option>{Array.from({ length: 8 }, (_, i) => i + 1).map(value => <option key={value} value={value}>Semester {value}</option>)}</select></label>
        </div>
      </div>}

      {step === 2 && <div className="onboarding-content">
        <p className="eyebrow">02 · AVAILABILITY</p>
        <h1>When can NEXUS realistically schedule you?</h1>
        <p className="muted">These are your normal available windows. Your actual calendar and future behavior can refine this later.</p>
        <div className="availability-block">
          <div className="availability-row">
            <strong>Weekdays</strong>
            <label>From<input type="time" value={form.weekdayStart} onChange={e => update("weekdayStart", e.target.value)} /></label>
            <label>To<input type="time" value={form.weekdayEnd} onChange={e => update("weekdayEnd", e.target.value)} /></label>
          </div>
          <div className="availability-row">
            <strong>Weekend</strong>
            <label>From<input type="time" value={form.weekendStart} onChange={e => update("weekendStart", e.target.value)} /></label>
            <label>To<input type="time" value={form.weekendEnd} onChange={e => update("weekendEnd", e.target.value)} /></label>
          </div>
        </div>
        <label>Timezone<select value={form.timezone} onChange={e => update("timezone", e.target.value)}>
          <option value="Asia/Kolkata">Asia/Kolkata</option>
          <option value="UTC">UTC</option>
          <option value="Asia/Singapore">Asia/Singapore</option>
          <option value="Europe/London">Europe/London</option>
          <option value="America/New_York">America/New_York</option>
          <option value="America/Los_Angeles">America/Los_Angeles</option>
        </select></label>
      </div>}

      {step === 3 && <div className="onboarding-content">
        <p className="eyebrow">03 · PLANNING STYLE</p>
        <h1>How should NEXUS structure your work?</h1>
        <p className="muted">This is a starting preference, not a permanent setting. NEXUS can learn from what you actually do.</p>
        <div className="choice-grid">
          {[
            ["focused", "Focused blocks", "Fewer, longer sessions with clear focus."],
            ["balanced", "Balanced", "Mix focused work with shorter sessions and breaks."],
            ["flexible", "Flexible", "Keep the plan adaptable around changing days."],
          ].map(([value, title, description]) =>
            <button type="button" key={value} className={form.planningStyle === value ? "choice active" : "choice"} onClick={() => update("planningStyle", value)}>
              <strong>{title}</strong><span>{description}</span>
            </button>
          )}
        </div>
      </div>}

      {error && <div className="error banner">{error}</div>}

      <div className="onboarding-actions">
        {step > 1 ? <button className="ghost" onClick={() => { setError(""); setStep(current => current - 1); }}>Back</button> : <span />}
        {step < 3
          ? <button className="primary" onClick={next}>Continue</button>
          : <button className="primary" onClick={finish} disabled={busy}>{busy ? "Saving profile…" : "Enter NEXUS"}</button>}
      </div>
    </section>
  </main>;
}

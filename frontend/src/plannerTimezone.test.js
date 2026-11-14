import test from "node:test";
import assert from "node:assert/strict";
import {
  AmbiguousProfileTimeError,
  isValidTimeZone,
  profileClock,
  profileDateTimeInput,
  profileLocalTimeCandidates,
  profileLocalTimeToISO,
  analyticsDateRange,
  profileDate,
  shiftAnalyticsDate,
} from "./plannerTimezone.js";

test("analytics calendar ranges use profile dates regardless of browser timezone", () => {
  const previous = process.env.TZ;
  try {
    process.env.TZ = "America/Los_Angeles";
    const now = new Date("2026-01-01T00:30:00Z");
    const profileToday = profileDate(now, "Asia/Kolkata");
    assert.equal(profileToday, "2026-01-01");
    assert.deepEqual(analyticsDateRange(profileToday, "week"), { start: "2025-12-29", end: "2026-01-04" });
    assert.deepEqual(analyticsDateRange(profileToday, "month"), { start: "2026-01-01", end: "2026-01-31" });
    assert.equal(shiftAnalyticsDate("2026-01-01", "week", -1), "2025-12-28");
    assert.equal(shiftAnalyticsDate("2026-01-01", "month", 1), "2026-02-28");
    assert.throws(() => profileDate(now, ""), /timezone is missing or invalid/);
  } finally {
    if (previous === undefined) delete process.env.TZ;
    else process.env.TZ = previous;
  }
});

test("planner displays and creates profile-local values when browser timezone differs", () => {
  const previous = process.env.TZ;
  try {
    process.env.TZ = "Asia/Tokyo";
    const instant = profileLocalTimeToISO("2026-07-14T09:30", "America/New_York");
    assert.equal(instant, "2026-07-14T13:30:00.000Z");
    assert.equal(profileDateTimeInput(instant, "America/New_York"), "2026-07-14T09:30");
    assert.equal(profileClock(instant, "America/New_York", "en-US"), "09:30 AM");
  } finally {
    if (previous === undefined) delete process.env.TZ;
    else process.env.TZ = previous;
  }
});

test("daily and weekly timestamp rendering share the same profile timezone conversion", () => {
  const instant = "2026-01-12T14:00:00.000Z";
  assert.equal(profileDateTimeInput(instant, "America/New_York"), "2026-01-12T09:00");
  assert.equal(profileDateTimeInput(instant, "America/New_York"), "2026-01-12T09:00");
});

test("editing a schedule value preserves the entered profile-local time", () => {
  const existing = "2026-07-14T13:30:00.000Z";
  const editValue = profileDateTimeInput(existing, "America/New_York");
  assert.equal(profileLocalTimeToISO(editValue, "America/New_York"), existing);
});

test("ambiguous profile-local times require deliberate offset selection", () => {
  const candidates = profileLocalTimeCandidates("2026-11-01T01:30", "America/New_York");
  assert.deepEqual(candidates.map(item => item.offset), ["UTC-04:00", "UTC-05:00"]);
  assert.throws(() => profileLocalTimeToISO("2026-11-01T01:30", "America/New_York"), AmbiguousProfileTimeError);
  assert.equal(profileLocalTimeToISO("2026-11-01T01:30", "America/New_York", "UTC-05:00"), "2026-11-01T06:30:00.000Z");
});

test("nonexistent profile-local times are rejected", () => {
  assert.throws(() => profileLocalTimeToISO("2026-03-08T02:30", "America/New_York"), /does not exist/);
});

test("changing browser timezone does not change profile-local interpretation", () => {
  const previous = process.env.TZ;
  try {
    process.env.TZ = "Pacific/Honolulu";
    const first = profileLocalTimeToISO("2026-07-14T09:00", "America/New_York");
    process.env.TZ = "Europe/Berlin";
    const second = profileLocalTimeToISO("2026-07-14T09:00", "America/New_York");
    assert.equal(first, second);
  } finally {
    if (previous === undefined) delete process.env.TZ;
    else process.env.TZ = previous;
  }
});

test("missing or invalid profile timezones fail explicitly", () => {
  assert.equal(isValidTimeZone(""), false);
  assert.equal(isValidTimeZone("Not/A_Zone"), false);
  assert.throws(() => profileLocalTimeToISO("2026-07-14T09:00", ""), /profile timezone is missing or invalid/);
});

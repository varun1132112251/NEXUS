const partsFormatter = (timeZone) => new Intl.DateTimeFormat("en-CA", {
  timeZone,
  year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
});

function partsAt(instant, formatter) {
  const values = Object.fromEntries(formatter.formatToParts(instant).map(({ type, value }) => [type, value]));
  return `${values.year}-${values.month}-${values.day}T${values.hour}:${values.minute}:${values.second}`;
}

function parseWallTime(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(value || "");
  if (!match) throw new Error("Enter a valid local date and time.");
  const [, year, month, day, hour, minute] = match.map(Number);
  const utcMillis = Date.UTC(year, month - 1, day, hour, minute);
  const check = new Date(utcMillis);
  if (check.getUTCFullYear() !== year || check.getUTCMonth() + 1 !== month || check.getUTCDate() !== day || check.getUTCHours() !== hour || check.getUTCMinutes() !== minute) {
    throw new Error("Enter a valid local date and time.");
  }
  return { wall: `${match[1]}-${match[2]}-${match[3]}T${match[4]}:${match[5]}:00`, utcMillis };
}

function offsetAt(instantMillis, formatter) {
  const local = partsAt(new Date(instantMillis), formatter);
  const localAsUtc = Date.parse(`${local}Z`);
  return localAsUtc - Math.floor(instantMillis / 1000) * 1000;
}

function offsetLabel(offsetMillis) {
  const totalMinutes = Math.abs(offsetMillis / 60000);
  const sign = offsetMillis >= 0 ? "+" : "-";
  return `UTC${sign}${String(Math.floor(totalMinutes / 60)).padStart(2, "0")}:${String(totalMinutes % 60).padStart(2, "0")}`;
}

export function isValidTimeZone(timeZone) {
  if (typeof timeZone !== "string" || !timeZone.trim()) return false;
  try { new Intl.DateTimeFormat("en", { timeZone }); return true; }
  catch { return false; }
}

export function profileDate(instant, timeZone) {
  if (!isValidTimeZone(timeZone)) throw new Error("Your profile timezone is missing or invalid. Update your profile before using the planner.");
  const fields = Object.fromEntries(new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" })
    .formatToParts(instant).map(({ type, value }) => [type, value]));
  return `${fields.year}-${fields.month}-${fields.day}`;
}

export function profileDateTimeInput(instant, timeZone) {
  if (!isValidTimeZone(timeZone)) throw new Error("Your profile timezone is missing or invalid. Update your profile before using the planner.");
  return partsAt(new Date(instant), partsFormatter(timeZone)).slice(0, 16);
}

export function profileClock(instant, timeZone, locale) {
  if (!isValidTimeZone(timeZone)) throw new Error("Your profile timezone is missing or invalid. Update your profile before using the planner.");
  return new Intl.DateTimeFormat(locale, { timeZone, hour: "2-digit", minute: "2-digit" }).format(new Date(instant));
}

export function addCalendarDays(date, amount) {
  const [year, month, day] = date.split("-").map(Number);
  const value = new Date(Date.UTC(year, month - 1, day + amount));
  return `${value.getUTCFullYear()}-${String(value.getUTCMonth() + 1).padStart(2, "0")}-${String(value.getUTCDate()).padStart(2, "0")}`;
}

export function analyticsDateRange(endDate, preset) {
  const [year, month, day] = endDate.split("-").map(Number);
  if (preset === "week") {
    const weekday = new Date(Date.UTC(year, month - 1, day)).getUTCDay();
    const start = addCalendarDays(endDate, -((weekday + 6) % 7));
    return { start, end: addCalendarDays(start, 6) };
  }
  if (preset === "month") {
    const start = `${year}-${String(month).padStart(2, "0")}-01`;
    const nextMonth = new Date(Date.UTC(year, month, 1));
    return { start, end: addCalendarDays(`${nextMonth.getUTCFullYear()}-${String(nextMonth.getUTCMonth() + 1).padStart(2, "0")}-01`, -1) };
  }
  return { start: endDate, end: endDate };
}

export function shiftAnalyticsDate(endDate, preset, direction) {
  if (preset === "day") return addCalendarDays(endDate, direction);
  const range = analyticsDateRange(endDate, preset);
  if (preset === "week") return addCalendarDays(range.end, direction * 7);
  const [year, month] = range.start.split("-").map(Number);
  const targetMonth = new Date(Date.UTC(year, month - 1 + direction, 1));
  const followingMonth = new Date(Date.UTC(targetMonth.getUTCFullYear(), targetMonth.getUTCMonth() + 1, 1));
  const followingFirst = `${followingMonth.getUTCFullYear()}-${String(followingMonth.getUTCMonth() + 1).padStart(2, "0")}-01`;
  return addCalendarDays(followingFirst, -1);
}

export class AmbiguousProfileTimeError extends Error {
  constructor(candidates) {
    super(`This local time occurs twice in your profile timezone. Choose ${candidates.map(candidate => candidate.offset).join(" or ")}.`);
    this.name = "AmbiguousProfileTimeError";
    this.candidates = candidates;
  }
}

export function profileLocalTimeCandidates(value, timeZone) {
  if (!isValidTimeZone(timeZone)) throw new Error("Your profile timezone is missing or invalid. Update your profile before using the planner.");
  const { wall, utcMillis } = parseWallTime(value);
  const formatter = partsFormatter(timeZone);
  const possibleOffsets = new Set();
  // Discover offsets surrounding this local date, then validate each candidate
  // by formatting it back in the requested IANA zone.
  for (let hours = -48; hours <= 48; hours += 6) possibleOffsets.add(offsetAt(utcMillis + hours * 3600000, formatter));
  return [...possibleOffsets].map(offset => utcMillis - offset)
    .filter(candidate => partsAt(new Date(candidate), formatter) === wall)
    .sort((a, b) => a - b)
    .map(candidate => ({ instant: new Date(candidate).toISOString(), offset: offsetLabel(offsetAt(candidate, formatter)) }));
}

export function profileLocalTimeToISO(value, timeZone, selectedOffset = null) {
  const candidates = profileLocalTimeCandidates(value, timeZone);
  if (candidates.length === 0) throw new Error("This local time does not exist in your profile timezone. Choose another time.");
  if (candidates.length > 1 && !selectedOffset) throw new AmbiguousProfileTimeError(candidates);
  const selected = candidates.length === 1 ? candidates[0] : candidates.find(candidate => candidate.offset === selectedOffset);
  if (!selected) throw new Error("Choose one of the listed timezone offsets for this ambiguous local time.");
  return selected.instant;
}

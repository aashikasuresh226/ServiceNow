/** When the homeowner is home: per-day time ranges in local time <-> the API's ISO ranges. */
import type { TimeRange } from './types';

export type LocalRange = { from: string; to: string }; // "17:30"
export type DayRanges = Record<string, LocalRange[]>; // "2026-11-21" -> ranges

export function dayKey(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

export function nextDays(count: number, from = new Date()): Date[] {
  return Array.from({ length: count }, (_, i) => {
    const d = new Date(from);
    d.setHours(0, 0, 0, 0);
    d.setDate(d.getDate() + i);
    return d;
  });
}

/** "17:30" -> [17, 30] */
export function parts(value: string): [number, number] {
  const [h = 0, m = 0] = value.split(':').map(Number);
  return [h, m];
}

export function formatClock(value: string): string {
  const [h, m] = parts(value);
  return `${h % 12 || 12}:${String(m).padStart(2, '0')} ${h < 12 ? 'AM' : 'PM'}`;
}

function minutes(value: string): number {
  const [h, m] = parts(value);
  return h * 60 + m;
}

function ymd(day: string): [number, number, number] {
  const [y = 1970, mo = 1, d = 1] = day.split('-').map(Number);
  return [y, mo, d];
}

function at(day: string, value: string): Date {
  const [y, mo, d] = ymd(day);
  const [h, mi] = parts(value);
  return new Date(y, mo - 1, d, h, mi);
}

/** Why a range can't be used, or null. */
export function rangeProblem(day: string, range: LocalRange, now = new Date()): string | null {
  if (minutes(range.to) <= minutes(range.from)) return 'End time must be after the start time';
  if (at(day, range.to) <= now) return 'This time has already passed';
  if (minutes(range.to) - minutes(range.from) < 30) return 'Make it at least 30 minutes';
  return null;
}

/** A sensible first range for a day: today from the next half hour, otherwise 9 to noon. */
export function suggestRange(day: string, now = new Date()): LocalRange {
  if (day !== dayKey(now)) return { from: '09:00', to: '12:00' };
  const start = Math.min(Math.ceil((now.getHours() * 60 + now.getMinutes() + 1) / 30) * 30, 21 * 60);
  const end = Math.min(start + 180, 23 * 60 + 55);
  const fmt = (t: number) => `${String(Math.floor(t / 60)).padStart(2, '0')}:${String(t % 60).padStart(2, '0')}`;
  return { from: fmt(start), to: fmt(end) };
}

export function toApi(days: DayRanges): TimeRange[] {
  return Object.entries(days).flatMap(([day, ranges]) =>
    ranges.map((r) => ({ start: at(day, r.from).toISOString(), end: at(day, r.to).toISOString() })));
}

export function fromApi(ranges: TimeRange[] | null | undefined): DayRanges {
  const out: DayRanges = {};
  for (const r of ranges ?? []) {
    const start = new Date(r.start);
    const end = new Date(r.end);
    const hhmm = (d: Date) => `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
    (out[dayKey(start)] ??= []).push({ from: hhmm(start), to: hhmm(end) });
  }
  return out;
}

/** "Today 5:00 – 8:30 PM" style lines for a summary. */
export function describeDay(day: string, ranges: LocalRange[] = [], now = new Date()): string {
  const [y, mo, d] = ymd(day);
  const date = new Date(y, mo - 1, d);
  const label = day === dayKey(now) ? 'Today'
    : day === dayKey(new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1)) ? 'Tomorrow'
      : date.toLocaleDateString(undefined, { weekday: 'short' });
  return `${label} ${ranges.map((r) => `${formatClock(r.from)} – ${formatClock(r.to)}`).join(', ')}`;
}

/** "5:00 – 6:00 PM": a one-hour arrival window, cut off when the homeowner leaves. */
export function arrivalWindow(arrivalAt: string, homeUntil?: string | null): string {
  const start = new Date(arrivalAt);
  let end = new Date(start.getTime() + 60 * 60 * 1000);
  if (homeUntil && new Date(homeUntil) < end) end = new Date(homeUntil);
  const t = (d: Date) => d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
  return `${t(start)} – ${t(end)}`;
}

/** The range the arrival falls in (when the homeowner is home until), if any. */
export function homeRangeFor(arrivalAt: string, ranges: TimeRange[] | null | undefined): TimeRange | null {
  const t = new Date(arrivalAt).getTime();
  return (ranges ?? []).find((r) => new Date(r.start).getTime() <= t && t <= new Date(r.end).getTime()) ?? null;
}

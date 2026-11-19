export function money(cents: number | null | undefined): string {
  if (cents == null) return '—';
  return `$${(cents / 100).toLocaleString('en-US', {
    minimumFractionDigits: cents % 100 === 0 ? 0 : 2,
    maximumFractionDigits: 2,
  })}`;
}

export function miles(km: number | null | undefined): string {
  if (km == null) return '';
  return `${(km * 0.621371).toFixed(1)} mi`;
}

export function minutesLabel(minutes: number | null | undefined): string {
  if (minutes == null) return '—';
  if (minutes < 60) return `${minutes} min`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m ? `${h} h ${m} min` : `${h} h`;
}

export function clockTime(minutesFromNow: number): string {
  const t = new Date(Date.now() + minutesFromNow * 60_000);
  return t.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
}

/** "Today 3:40 PM", "Tomorrow 8:15 AM" or "Thu 8:15 AM". */
export function visitTime(iso: string): string {
  const t = new Date(iso);
  const time = t.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
  const day = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const diff = Math.round((day(t) - day(new Date())) / 86_400_000);
  if (diff <= 0) return `Today ${time}`;
  if (diff === 1) return `Tomorrow ${time}`;
  return `${t.toLocaleDateString('en-US', { weekday: 'short' })} ${time}`;
}

/** True when the visit is a later booking rather than "on the way now". */
export function isScheduled(iso: string | null | undefined): boolean {
  return Boolean(iso) && new Date(iso as string).getTime() - Date.now() > 2 * 60 * 60_000;
}

export function countdown(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${s.toString().padStart(2, '0')}`;
}

export function formatPhone(e164: string | null | undefined): string {
  if (!e164) return '—';
  const d = e164.replace(/\D/g, '');
  if (d.length === 11 && d.startsWith('1')) {
    return `(${d.slice(1, 4)}) ${d.slice(4, 7)}-${d.slice(7)}`;
  }
  return e164;
}

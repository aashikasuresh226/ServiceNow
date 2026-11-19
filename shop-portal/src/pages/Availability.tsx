/**
 * Today's board: each tech's open hours, jobs booked through the app (with the
 * customer once the shop accepts), and manual busy time. Each tech also has a
 * private calendar link to subscribe to from their phone.
 */
import { useEffect, useState } from 'react';

import { Avatar } from '../components/Icon';
import { Button, ErrorAlert } from '../components/ui';
import { api } from '../lib/api';
import { clock, useAction, useLiveData, usePortal } from '../lib/hooks';
import type { CalendarLink, Technician } from '../lib/types';

const START_HOUR = 6;
const END_HOUR = 22;
const SPAN_MS = (END_HOUR - START_HOUR) * 3_600_000;

function dayStart(offset: number): number {
  const d = new Date();
  d.setDate(d.getDate() + offset);
  d.setHours(START_HOUR, 0, 0, 0);
  return d.getTime();
}

function isoDay(offset: number): string {
  const d = new Date();
  d.setDate(d.getDate() + offset);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function dayName(offset: number): string {
  if (offset === 0) return 'Today';
  if (offset === 1) return 'Tomorrow';
  const d = new Date();
  d.setDate(d.getDate() + offset);
  return d.toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' });
}

export function AvailabilityPage() {
  const { me } = usePortal();
  const [offset, setOffset] = useState(0);
  const board = useLiveData(() => api.availability(offset ? isoDay(offset) : undefined), 5000);
  useEffect(() => { void board.reload(); }, [offset]); // eslint-disable-line react-hooks/exhaustive-deps
  const position = (iso: string) =>
    Math.min(100, Math.max(0, ((new Date(iso).getTime() - dayStart(offset)) / SPAN_MS) * 100));
  const busy = useAction(async (id: string, minutes: number) => { await api.markBusy(id, minutes); await board.reload(); });
  const free = useAction(async (id: string) => { await api.clearBusy(id); await board.reload(); });
  const nowPct = offset === 0 ? position(new Date().toISOString()) : -1;
  const hours = Array.from({ length: (END_HOUR - START_HOUR) / 2 + 1 }, (_, i) => START_HOUR + i * 2);
  const synced = me.shop.scheduling_last_synced_at;

  return (
    <>
      <div className="row between">
        <div className="row" style={{ gap: 8 }}>
          <h1>Availability · {dayName(offset)}</h1>
          <Button size="small" disabled={offset === 0} onClick={() => setOffset((o) => o - 1)} aria-label="Previous day">‹</Button>
          <Button size="small" disabled={offset >= 6} onClick={() => setOffset((o) => o + 1)} aria-label="Next day">›</Button>
        </div>
        <span className="badge primary">
          {me.shop.scheduling_provider === 'none' ? 'From working hours'
            : synced ? `Synced ${clock(synced)}` : 'Waiting for first sync'}
        </span>
      </div>
      <p className="muted">Open time is offered to nearby homeowners. Jobs booked in the app are added
        here automatically. Mark a tech busy for walk-in or phone jobs.</p>
      <ErrorAlert message={board.error ?? busy.error ?? free.error} />
      {board.data && !board.data.length ? (
        <div className="card soft">No technicians yet. Add them on the Technicians page.</div>
      ) : null}
      <div className="card table-wrap">
        {/* One grid for the header and every row, so the hour labels sit exactly over the bars. */}
        <div className="board-grid">
          <span aria-hidden="true" />
          <div className="hour-axis" aria-hidden="true">
            {hours.map((h, i) => {
              const left = ((h - START_HOUR) / (END_HOUR - START_HOUR)) * 100;
              if (nowPct >= 0 && Math.abs(left - nowPct) < 5) return null; // the "now" time sits there
              return (
                <span key={h} className={`small muted${i === 0 ? ' first' : i === hours.length - 1 ? ' last' : ''}`} style={{ left: `${left}%` }}>
                  {h % 12 || 12}{h < 12 ? 'a' : 'p'}
                </span>
              );
            })}
            {nowPct >= 0 ? (
              <span className="now-label" style={{ left: `${nowPct}%` }}>
                {new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}
              </span>
            ) : null}
          </div>
          <span aria-hidden="true" />
          {board.data?.map((d) => (
            <div key={d.technician.id} className="board-row">
              <div className="row" style={{ flexWrap: 'nowrap', minWidth: 0 }}>
                <Avatar name={d.technician.name} size={30} />
                <div style={{ minWidth: 0 }}>
                  <strong style={{ display: 'block', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{d.technician.name}</strong>
                  <span className={`badge ${d.on_job ? 'amber' : d.free_now ? 'success' : 'neutral'}`} style={{ padding: '1px 8px' }}>
                    {!d.technician.is_active ? 'Inactive' : d.on_job ? 'On a job' : d.free_now ? 'Free now' : 'Busy / off'}
                  </span>
                </div>
              </div>
              <div className="timeline" aria-label={`${d.technician.name}'s schedule today`}>
                {d.blocks.filter((b) => b.kind === 'shift').map((b) => (
                  <div key={`s${b.starts_at}`} className="block shift"
                    style={{ left: `${position(b.starts_at)}%`, width: `${position(b.ends_at) - position(b.starts_at)}%` }}>Open</div>
                ))}
                {d.blocks.filter((b) => b.kind === 'busy').map((b) => (
                  <div key={`b${b.starts_at}${b.label ?? ''}`} className={`block busy${b.source === 'job' ? ' job' : ''}`}
                    title={`${clock(b.starts_at)}–${clock(b.ends_at)}${b.label ? ` · ${b.label}` : ''}`}
                    style={{ left: `${position(b.starts_at)}%`, width: `${Math.max(1, position(b.ends_at) - position(b.starts_at))}%` }}>
                    {b.source === 'job' ? b.label ?? 'Job' : 'Busy'}
                  </div>
                ))}
                {nowPct >= 0 ? <div className="now" style={{ left: `${nowPct}%` }} aria-hidden="true" /> : null}
              </div>
              <div className="row" style={{ flexWrap: 'nowrap', gap: 6 }}>
                <Button size="small" onClick={() => busy.run(d.technician.id, 45)} disabled={!d.technician.is_active}>Busy 45m</Button>
                <Button size="small" onClick={() => free.run(d.technician.id)}>Free now</Button>
                <CalendarButton tech={d.technician} />
              </div>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}

function CalendarButton({ tech }: { tech: Technician }) {
  const [link, setLink] = useState<CalendarLink | null>(null);
  const [copied, setCopied] = useState(false);
  const load = useAction(async (rotate: boolean) => setLink(await api.calendarLink(tech.id, rotate)));
  if (!link) {
    return <Button size="small" busy={load.busy} onClick={() => load.run(false)}>Calendar link</Button>;
  }
  return (
    <>
    <Button size="small" onClick={() => setLink(null)}>Calendar link</Button>
    <div className="calendar-backdrop" onClick={(e) => { if (e.target === e.currentTarget) setLink(null); }}>
    <div className="calendar-pop card" role="dialog" aria-modal="true" aria-label={`${tech.name}'s calendar link`}>
      <strong className="small">Subscribe to {tech.name.split(' ')[0]}'s jobs</strong>
      <input className="input small" readOnly value={link.url} onFocus={(e) => e.currentTarget.select()} aria-label="Calendar feed URL" />
      <div className="row" style={{ gap: 6 }}>
        <Button size="small" onClick={async () => { await navigator.clipboard.writeText(link.url); setCopied(true); }}>
          {copied ? 'Copied' : 'Copy'}
        </Button>
        <a className="btn small" href={link.webcal_url}>Apple / Outlook</a>
        <a className="btn small" href={link.google_url} target="_blank" rel="noreferrer">Google Calendar</a>
        <Button size="small" onClick={() => setLink(null)}>Close</Button>
      </div>
      <span className="small muted">Google Calendar needs the API to be reachable on the internet
        (not localhost). Anyone with this link sees the jobs. <a href="#new" onClick={(e) => { e.preventDefault(); void load.run(true); }}>Make a new link</a> to revoke old ones.</span>
    </div>
    </div>
    </>
  );
}

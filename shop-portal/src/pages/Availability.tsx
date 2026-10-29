/** Today's board: each tech's shifts and bookings, with quick manual busy/free controls. */
import { Avatar } from '../components/Icon';
import { Button, ErrorAlert } from '../components/ui';
import { api } from '../lib/api';
import { clock, useAction, useLiveData, usePortal } from '../lib/hooks';

const START_HOUR = 6;
const END_HOUR = 22;
const SPAN_MS = (END_HOUR - START_HOUR) * 3_600_000;

function dayStart(): number {
  const d = new Date();
  d.setHours(START_HOUR, 0, 0, 0);
  return d.getTime();
}

function position(iso: string): number {
  return Math.min(100, Math.max(0, ((new Date(iso).getTime() - dayStart()) / SPAN_MS) * 100));
}

export function AvailabilityPage() {
  const { me } = usePortal();
  const board = useLiveData(() => api.availability(), 5000);
  const busy = useAction(async (id: string, minutes: number) => { await api.markBusy(id, minutes); await board.reload(); });
  const free = useAction(async (id: string) => { await api.clearBusy(id); await board.reload(); });
  const nowPct = position(new Date().toISOString());
  const hours = Array.from({ length: (END_HOUR - START_HOUR) / 2 + 1 }, (_, i) => START_HOUR + i * 2);
  const synced = me.shop.scheduling_last_synced_at;

  return (
    <>
      <div className="row between">
        <h1>Live availability · Today</h1>
        <span className="badge primary">
          {me.shop.scheduling_provider === 'none' ? 'From working hours'
            : synced ? `Synced ${clock(synced)}` : 'Waiting for first sync'}
        </span>
      </div>
      <p className="muted">Open time is offered to nearby homeowners. Mark a tech busy for walk-in or phone jobs.</p>
      <ErrorAlert message={board.error ?? busy.error ?? free.error} />
      <div className="card table-wrap">
        <div style={{ minWidth: 720, display: 'grid', gap: 10 }}>
          <div className="row" style={{ paddingLeft: 200, gap: 0 }}>
            {hours.map((h) => (
              <span key={h} className="small muted" style={{ flex: 1 }}>{h % 12 || 12}{h < 12 ? 'a' : 'p'}</span>
            ))}
          </div>
          {board.data?.map((d) => (
            <div key={d.technician.id} className="row" style={{ gap: 12, flexWrap: 'nowrap' }}>
              <div className="row" style={{ width: 188, flexWrap: 'nowrap' }}>
                <Avatar name={d.technician.name} size={30} />
                <div style={{ minWidth: 0 }}>
                  <strong style={{ display: 'block', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{d.technician.name}</strong>
                  <span className={`badge ${d.on_job ? 'amber' : d.free_now ? 'success' : 'neutral'}`} style={{ padding: '1px 8px' }}>
                    {!d.technician.is_active ? 'Inactive' : d.on_job ? 'On a job' : d.free_now ? 'Free now' : 'Busy / off'}
                  </span>
                </div>
              </div>
              <div className="timeline" style={{ flex: 1 }} aria-label={`${d.technician.name}'s schedule today`}>
                {d.blocks.filter((b) => b.kind === 'shift').map((b) => (
                  <div key={`s${b.starts_at}`} className="block shift"
                    style={{ left: `${position(b.starts_at)}%`, width: `${position(b.ends_at) - position(b.starts_at)}%` }}>Open</div>
                ))}
                {d.blocks.filter((b) => b.kind === 'busy').map((b) => (
                  <div key={`b${b.starts_at}`} className="block busy" title={`${clock(b.starts_at)}–${clock(b.ends_at)}`}
                    style={{ left: `${position(b.starts_at)}%`, width: `${Math.max(1, position(b.ends_at) - position(b.starts_at))}%` }}>Busy</div>
                ))}
                <div className="now" style={{ left: `${nowPct}%` }} aria-hidden="true" />
              </div>
              <div className="row" style={{ flexWrap: 'nowrap', gap: 6 }}>
                <Button size="small" onClick={() => busy.run(d.technician.id, 45)} disabled={!d.technician.is_active}>Busy 45m</Button>
                <Button size="small" onClick={() => free.run(d.technician.id)}>Free now</Button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}

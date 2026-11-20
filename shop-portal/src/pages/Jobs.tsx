/** Incoming offers (accept/decline with countdown) and active jobs (progress, quote, complete). */
import { useState } from 'react';

import { Avatar, Icon } from '../components/Icon';
import { Button, Empty, ErrorAlert } from '../components/ui';
import { api } from '../lib/api';
import { clock, countdownLabel, label, money, useAction, useCountdown, useLiveData, usePortal, visitTime } from '../lib/hooks';
import type { Job, Message, OutsideJob, TechOption } from '../lib/types';

/** +14045550199 -> (404) 555-0199 */
function prettyPhone(e164: string): string {
  const d = e164.replace(/\D/g, '');
  return d.length === 11 && d.startsWith('1') ? `(${d.slice(1, 4)}) ${d.slice(4, 7)}-${d.slice(7)}` : e164;
}

const STATUS_LABEL: Record<string, string> = {
  offered: 'New offer',
  dispatched: 'Dispatched',
  en_route: 'En route',
  on_site: 'On site',
  quoted: 'Waiting for approval',
  in_progress: 'Approved · in progress',
  completed: 'Completed',
};

function JobSummary({ job }: { job: Job }) {
  const { options } = usePortal();
  return (
    <>
    {job.picked_by_customer ? (
      <p className="badge success" style={{ alignSelf: 'flex-start', width: 'fit-content' }}>Customer chose you</p>
    ) : null}
    <div className="row" style={{ alignItems: 'flex-start', gap: 16 }}>
      {job.photos[0] ? (
        <img className="photo-thumb" src={job.photos[0].url} alt="Homeowner's photo of the unit" />
      ) : (
        <svg className="photo-thumb" viewBox="0 0 120 100" role="img" aria-label="No photo">
          <rect x="12" y="10" width="96" height="76" rx="6" fill="#fff" stroke="#5B6372" strokeWidth="2" />
          <circle cx="54" cy="52" r="24" fill="#fff" stroke="#5B6372" strokeWidth="2" />
          <rect x="88" y="28" width="14" height="22" rx="2" fill="#DCE5FB" stroke="#1D4ED8" strokeWidth="2" />
        </svg>
      )}
      <div className="stack spacer" style={{ gap: 4, minWidth: 220 }}>
        <span className="row small strong" style={{ color: 'var(--primary)', gap: 4 }}>
          {job.diagnosis?.ai_used === false
            ? <>Request details · photo analysis off</>
            : <><Icon name="sparkle" size={14} /> AI summary</>}
        </span>
        <span><span className="muted">Unit:</span> {job.unit?.brand ?? 'Unknown brand'} {job.unit?.model_number ?? ''}
          {job.unit ? ` · ${label(options, 'equipment_types', job.unit.equipment_type)}` : ''}
          {job.unit?.manufacture_year ? ` · made ${job.unit.manufacture_year}` : ''}
          {job.unit?.approx_age_years != null ? ` · ~${job.unit.approx_age_years} yrs` : ''}
          {job.unit?.tonnage ? ` · ${job.unit.tonnage} ton` : ''}
          {job.unit?.refrigerant ? ` · ${job.unit.refrigerant}` : ''}</span>
        {job.diagnosis?.visible_issues?.length ? (
          <span><span className="muted">Seen in photo:</span> {job.diagnosis.visible_issues.join('; ')}</span>
        ) : null}
        <span><span className="muted">Likely issue:</span> {job.diagnosis?.primary_issue_label ?? 'Needs diagnosis'}</span>
        <span><span className="muted">Homeowner says:</span>{' '}
          {job.description ? `“${job.description}”` : job.symptoms.map((s) => label(options, 'symptoms', s)).join(', ')}</span>
        <span title={job.estimate.basis ?? undefined}><span className="muted">Shown to homeowner:</span>{' '}
          {job.estimate.source === 'visit_only'
            ? `${money(job.estimate.low_cents)} visit only (no estimate)`
            : job.estimate.high_cents && job.estimate.low_cents != null && job.estimate.high_cents > job.estimate.low_cents
              ? `${money(job.estimate.low_cents)}–${money(job.estimate.high_cents)}`
              : `from ${money(job.estimate.low_cents)}`}</span>
      </div>
    </div>
    </>
  );
}

export function OfferCard({ job, onChanged }: { job: Job; onChanged: () => void }) {
  const { options, me } = usePortal();
  const mode = me?.shop.dispatch_mode ?? 'platform';
  const seconds = useCountdown(job.offer_expires_at);
  const techs = useLiveData(() => (mode === 'software' ? Promise.resolve([] as TechOption[]) : api.technicianOptions(job.id)));
  const [techId, setTechId] = useState<string>('');
  const chosen = techId || techs.data?.find((t) => t.suggested)?.technician_id || '';
  const accept = useAction(async () => {
    const suggested = techs.data?.find((t) => t.suggested)?.technician_id;
    await api.accept(job.id, chosen && chosen !== suggested ? chosen : undefined);
    onChanged();
  });
  const decline = useAction(async () => { await api.decline(job.id); onChanged(); });

  return (
    <section className="card offer" aria-label="New job offer">
      <div className="row between">
        <h2>New request · {job.area_label}</h2>
        <span className="badge amber">Respond in {seconds != null ? countdownLabel(seconds) : '—'}</span>
      </div>
      {job.offered_to_several ? (
        <p className="notice small" role="status"><strong>Offered to a few nearby shops at once.</strong> The first to accept gets it.</p>
      ) : null}
      <JobSummary job={job} />
      {job.arrival_at && new Date(job.arrival_at).getTime() - Date.now() > 2 * 3600_000 ? (
        <p className="notice small">Scheduled visit: <strong>{visitTime(job.arrival_at)}</strong> (your earliest
          opening). It's held on the calendar until you respond.</p>
      ) : null}
      {mode === 'software' ? (
        <p className="small" style={{ border: '1px solid var(--line)', borderRadius: 10, padding: 12 }}>
          <Icon name="plug" size={14} /> Accepting creates this job in <strong>Housecall Pro</strong> for{' '}
          {job.arrival_at ? visitTime(job.arrival_at) : 'the earliest opening'}, with the photos and notes. Assign the
          technician there; the customer is told who's coming as soon as you do.
        </p>
      ) : (
        <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0, gap: 8 }}>
          <legend className="label" style={{ marginBottom: 6 }}>
            {mode === 'office' ? 'Who should go?' : 'Technician (suggested: soonest qualified)'}
          </legend>
          {techs.data === null ? <p className="small muted">Checking who's free…</p> : null}
          {techs.data?.map((t) => (
            <label key={t.technician_id} className={`choice ${chosen === t.technician_id ? 'selected' : ''}`}
              style={{ opacity: t.available ? 1 : 0.55 }}>
              <input type="radio" name={`tech-${job.id}`} checked={chosen === t.technician_id} disabled={!t.available}
                onChange={() => setTechId(t.technician_id)} />
              <span className="spacer">
                <strong>{t.name}</strong>{t.suggested ? <span className="badge primary small" style={{ marginLeft: 6 }}>Suggested</span> : null}<br />
                <span className="small muted">
                  {t.available
                    ? `Arrives ${t.arrival_at ? visitTime(t.arrival_at) : 'soon'}${t.distance_km != null ? ` · ${(t.distance_km * 0.621371).toFixed(1)} mi away` : ''}`
                    : t.reason}
                </span>
              </span>
            </label>
          ))}
        </fieldset>
      )}
      {options?.features.payments ? (
        <p className="small muted">You'll receive {money(job.payout_cents)} after the platform fee (based on the estimate; final price set on site).</p>
      ) : (
        <p className="small muted">Accepting adds the job and customer details to the technician's calendar. You set the final price on site and collect payment directly.</p>
      )}
      <ErrorAlert message={accept.error ?? decline.error ?? techs.error} />
      <div className="row" style={{ justifyContent: 'flex-end' }}>
        <Button busy={decline.busy} onClick={() => decline.run()}>Decline</Button>
        <Button variant="primary" icon="truck" busy={accept.busy} onClick={() => accept.run()}>
          {mode === 'software' ? 'Accept & send to Housecall Pro' : 'Accept & dispatch'}
        </Button>
      </div>
    </section>
  );
}

function ActiveJobCard({ job, onChanged }: { job: Job; onChanged: () => void }) {
  const { options } = usePortal();
  const paymentsOn = options?.features.payments ?? false;
  const [price, setPrice] = useState('');
  const [notes, setNotes] = useState('');
  const act = useAction(async (fn: () => Promise<unknown>) => { await fn(); onChanged(); });
  const cents = Math.round(parseFloat(price || '0') * 100);

  return (
    <section className="card" aria-label={`Job for ${job.customer_first_name ?? 'customer'}`}>
      <div className="row between">
        <div className="row">
          <Avatar name={job.technician_name ?? ''} size={32} />
          <div>
            <strong>{job.technician_confirmed ? job.technician_name : 'Technician not assigned yet'}</strong>
            <p className="small muted">{job.customer_first_name ?? 'Customer'} · {job.address ?? job.area_label}</p>
          </div>
        </div>
        <span className={`badge ${job.status === 'completed' ? 'success' : job.status === 'quoted' ? 'amber' : 'primary'}`}>
          {STATUS_LABEL[job.status]}
        </span>
      </div>
      {job.technician_flag ? (
        <div className="alert" role="alert">
          <Icon name="alert" size={18} />
          <span><strong>{job.technician_name} can't make this job:</strong> “{job.technician_flag}”. Call the
            customer or reassign it.</span>
        </div>
      ) : null}
      {job.instant_booked || job.external_job_id ? (
        <p className="row small">
          {job.instant_booked ? <span className="badge success">Instant book</span> : null}
          {job.external_job_id ? <span className="badge neutral"><Icon name="plug" size={12} /> In Housecall Pro</span> : null}
          {job.external_job_id && !job.technician_confirmed ? (
            <span className="muted">Assign the technician in Housecall Pro; the customer is updated automatically.</span>
          ) : null}
        </p>
      ) : null}
      {job.external_error ? (
        <div className="alert" role="alert"><Icon name="alert" size={18} />
          <span><strong>Couldn't send this job to Housecall Pro:</strong> {job.external_error}. We'll retry every minute.</span>
        </div>
      ) : null}
      {job.driving ? (
        <p className="row small"><span className="badge primary"><Icon name="truck" size={13} /> On the way</span>
          <span className="muted">The customer sees the technician's live location until they arrive.</span></p>
      ) : null}
      <JobSummary job={job} />
      {job.customer_phone ? (
        <p className="row small"><Icon name="phone" size={14} /> <a href={`tel:${job.customer_phone}`}>Call {job.customer_first_name ?? 'customer'} · {prettyPhone(job.customer_phone)}</a></p>
      ) : null}
      {job.chat_open ? <ChatPanel job={job} /> : null}

      {job.status === 'dispatched' ? (
        <div className="row"><Button variant="primary" icon="truck" busy={act.busy} onClick={() => act.run(() => api.enRoute(job.id))}>Mark en route</Button></div>
      ) : null}
      {job.status === 'en_route' ? (
        <div className="row"><Button variant="primary" icon="mapPin" busy={act.busy} onClick={() => act.run(() => api.onSite(job.id))}>Arrived on site</Button></div>
      ) : null}
      {job.status === 'on_site' ? (
        <form className="grid-2" style={{ alignItems: 'end' }}
          onSubmit={(e) => { e.preventDefault(); void act.run(() => api.quote(job.id, cents, notes)); }}>
          <div className="field">
            <label htmlFor={`price-${job.id}`}>Final price ($)</label>
            <input id={`price-${job.id}`} className="input" inputMode="decimal" value={price}
              placeholder={((job.estimate.low_cents ?? 0) / 100).toFixed(0)} onChange={(e) => setPrice(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor={`notes-${job.id}`}>What was wrong / what you'll do</label>
            <input id={`notes-${job.id}`} className="input" value={notes} onChange={(e) => setNotes(e.target.value)}
              placeholder="e.g. Replaced run capacitor" />
          </div>
          <Button type="submit" variant="primary" busy={act.busy} disabled={cents <= 0}>Send price to homeowner</Button>
        </form>
      ) : null}
      {job.status === 'quoted' ? (
        <p className="notice small">Sent {money(job.quote?.final_price_cents)} to the homeowner. Waiting for them to approve in the app.</p>
      ) : null}
      {job.status === 'in_progress' ? (
        <div className="row">
          <span className="muted small">Approved {money(job.quote?.final_price_cents)}.</span>
          <Button variant="primary" icon="check" busy={act.busy} onClick={() => act.run(() => api.complete(job.id))}>{paymentsOn ? 'Mark complete & charge' : 'Mark complete'}</Button>
        </div>
      ) : null}
      {job.status === 'completed' ? (
        job.payment.captured_cents != null ? (
          <p className="small"><strong>Charged {money(job.payment.captured_cents)}</strong> · you receive {money(job.payout_cents)}</p>
        ) : (
          <p className="small"><strong>Done · {money(job.quote?.final_price_cents)}</strong> · collect payment directly</p>
        )
      ) : null}
      <ErrorAlert message={act.error} />
    </section>
  );
}

/** The office's view of the customer chat (the technician joins if allowed). */
function ChatPanel({ job }: { job: Job }) {
  const [open, setOpen] = useState(false);
  const messages = useLiveData(() => (open ? api.messages(job.id) : Promise.resolve([] as Message[])), open ? 4000 : 0);
  const [text, setText] = useState('');
  const send = useAction(async () => {
    await api.sendMessage(job.id, text);
    setText('');
    await messages.reload();
  });
  if (!open) {
    return <div className="row"><Button size="small" icon="chat" onClick={() => setOpen(true)}>Messages with {job.customer_first_name ?? 'customer'}</Button></div>;
  }
  return (
    <div className="stack" style={{ border: '1px solid var(--line)', borderRadius: 10, padding: 12, gap: 8 }}>
      <div className="row between"><strong className="small">Messages</strong>
        <Button size="small" onClick={() => setOpen(false)}>Hide</Button></div>
      <div className="chat" aria-live="polite">
        {messages.data?.length ? messages.data.map((m) => (
          <div key={m.id} className={`bubble ${m.sender === 'shop' ? 'us' : 'them'}`}>
            <span className="who">{m.sender === 'homeowner' ? (m.sender_name ?? 'Customer') : m.sender === 'technician' ? `${m.sender_name ?? 'Technician'} (tech)` : 'Your office'}</span>
            {m.body}
          </div>
        )) : <p className="small muted">No messages yet.</p>}
      </div>
      <form className="row" style={{ flexWrap: 'nowrap' }} onSubmit={(e) => { e.preventDefault(); if (text.trim()) void send.run(); }}>
        <label htmlFor={`msg-${job.id}`} className="sr-only">Message</label>
        <input id={`msg-${job.id}`} className="input" value={text} maxLength={1000} placeholder="Write a message"
          onChange={(e) => setText(e.target.value)} />
        <Button type="submit" variant="primary" icon="send" busy={send.busy} disabled={!text.trim()}>Send</Button>
      </form>
      <ErrorAlert message={send.error ?? messages.error} />
    </div>
  );
}

export function JobsPage() {
  const offers = useLiveData(() => api.jobs(['offered']), 4000);
  const active = useLiveData(() => api.jobs(['dispatched', 'en_route', 'on_site', 'quoted', 'in_progress']), 4000);
  const done = useLiveData(() => api.jobs(['completed']), 10000);
  const { me } = usePortal();
  const hcp = me.shop.scheduling_provider === 'housecall_pro';
  const outside = useLiveData(() => (hcp ? api.outsideJobs() : Promise.resolve([] as OutsideJob[])), 15000);
  const reloadAll = () => { void offers.reload(); void active.reload(); void done.reload(); };

  return (
    <>
      <h1>Jobs</h1>
      <ErrorAlert message={offers.error ?? active.error} />
      {offers.data?.map((j) => <OfferCard key={j.id} job={j} onChanged={reloadAll} />)}
      <h2>Active</h2>
      {active.data?.length ? active.data.map((j) => <ActiveJobCard key={j.id} job={j} onChanged={reloadAll} />)
        : <div className="card"><Empty icon="jobs">No active jobs. New offers appear here automatically.</Empty></div>}
      {hcp ? (
        <>
          <h2>In Housecall Pro</h2>
          <p className="muted small" style={{ marginTop: -12 }}>
            Jobs your office booked in Housecall Pro, copied every minute. Assigned technicians see them in the technician app.
          </p>
          <ErrorAlert message={outside.error} />
          {outside.data?.length ? <OutsideTable jobs={outside.data} /> : (
            <div className="card"><Empty icon="calendar">No Housecall Pro jobs from yesterday through the next week.</Empty></div>
          )}
        </>
      ) : null}
      <h2>Completed</h2>
      {done.data?.length ? (
        <div className="card table-wrap">
          <table className="table">
            <thead><tr><th>Date</th><th>Technician</th><th>Work</th><th>Price</th><th>Your payout</th></tr></thead>
            <tbody>
              {done.data.map((j) => (
                <tr key={j.id}>
                  <td>{new Date(j.created_at).toLocaleDateString()}</td>
                  <td>
                    {j.technician_name}
                    {j.picked_by_customer ? <span className="badge success small" style={{ marginLeft: 6 }}>Customer chose you</span> : null}
                  </td>
                  <td>{j.diagnosis?.primary_issue_label ?? 'Service'}</td>
                  <td>{money(j.payment.captured_cents ?? j.quote?.final_price_cents)}</td>
                  <td><strong>{j.payment.captured_cents != null ? money(j.payout_cents) : 'Collect directly'}</strong></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <p className="muted">No completed jobs yet.</p>}
    </>
  );
}

function OutsideTable({ jobs }: { jobs: OutsideJob[] }) {
  return (
    <div className="card table-wrap">
      <table className="table">
        <thead><tr><th>When</th><th>Customer</th><th>Job</th><th>Technician</th><th>In the app</th><th>Housecall Pro</th></tr></thead>
        <tbody>
          {jobs.map((j) => (
            <tr key={j.id}>
              <td>{j.starts_at ? visitTime(j.starts_at) : <span className="muted">Not scheduled</span>}</td>
              <td>
                {j.customer_name ?? 'Customer'}
                {j.customer_uses_app ? <span className="badge success small" style={{ marginLeft: 6 }}>Uses the app</span> : null}
                {j.address ? <span className="muted small" style={{ display: 'block' }}>{j.address}</span> : null}
              </td>
              <td className="small">{j.invoice_number ? `#${j.invoice_number} · ` : ''}{j.description ?? '—'}</td>
              <td>{j.technician_name ?? <span className="muted">Unassigned</span>}</td>
              <td className="small"><AppProgress job={j} /></td>
              <td className="small" style={{ textTransform: 'capitalize' }}>{j.work_status || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** What the technician has done on a Housecall Pro job in our app. */
function AppProgress({ job }: { job: OutsideJob }) {
  const at = (iso: string | null) => (iso ? clock(iso) : '');
  const text = {
    '': null,
    en_route: `On the way ${at(job.on_my_way_at)}`,
    on_site: `Arrived ${at(job.arrived_at)}`,
    working: `Working since ${at(job.started_at)}`,
    finished: `Finished ${at(job.finished_at)}`,
  }[job.app_status];
  if (!text) return <span className="muted">—</span>;
  return (
    <span>
      <span className={`badge ${job.app_status === 'finished' ? 'success' : 'amber'} small`}>{text}</span>
      {job.app_status === 'finished' && !/complete/i.test(job.work_status) ? (
        <span className="muted" style={{ display: 'block' }}>Invoice it in Housecall Pro</span>
      ) : null}
      {job.unsent ? <span className="muted" style={{ display: 'block' }}>{job.unsent} waiting to send</span> : null}
    </span>
  );
}

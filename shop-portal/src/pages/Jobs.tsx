/** Incoming offers (accept/decline with countdown) and active jobs (progress, quote, complete). */
import { useState } from 'react';

import { Avatar, Icon } from '../components/Icon';
import { Button, Empty, ErrorAlert } from '../components/ui';
import { api } from '../lib/api';
import { countdownLabel, label, money, useAction, useCountdown, useLiveData, usePortal } from '../lib/hooks';
import type { Job } from '../lib/types';

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
          <Icon name="sparkle" size={14} /> AI summary
        </span>
        <span><span className="muted">Unit:</span> {job.unit?.brand ?? 'Unknown brand'} {job.unit?.model_number ?? ''}
          {job.unit ? ` · ${label(options, 'equipment_types', job.unit.equipment_type)}` : ''}
          {job.unit?.approx_age_years != null ? ` · ~${job.unit.approx_age_years} yrs` : ''}</span>
        <span><span className="muted">Likely issue:</span> {job.diagnosis?.primary_issue_label ?? 'Needs diagnosis'}</span>
        <span><span className="muted">Homeowner says:</span>{' '}
          {job.description ? `“${job.description}”` : job.symptoms.map((s) => label(options, 'symptoms', s)).join(', ')}</span>
        <span><span className="muted">Quoted to homeowner:</span> from {money(job.estimate.low_cents)}</span>
      </div>
    </div>
  );
}

export function OfferCard({ job, onChanged }: { job: Job; onChanged: () => void }) {
  const { options } = usePortal();
  const seconds = useCountdown(job.offer_expires_at);
  const techs = useLiveData(() => api.availability());
  const [techId, setTechId] = useState<string>('');
  const accept = useAction(async () => { await api.accept(job.id, techId || undefined); onChanged(); });
  const decline = useAction(async () => { await api.decline(job.id); onChanged(); });
  const freeTechs = (techs.data ?? []).filter((d) => d.free_now && d.technician.id !== job.technician_id);

  return (
    <section className="card offer" aria-label="New job offer">
      <div className="row between">
        <h2>New request · {job.area_label}</h2>
        <span className="badge amber">Respond in {seconds != null ? countdownLabel(seconds) : '—'}</span>
      </div>
      <JobSummary job={job} />
      {job.soft_skills.length ? (
        <div className="row small">
          <span className="muted">Wants:</span>
          {job.soft_skills.map((s) => <span key={s} className="badge primary">{label(options, 'soft_skills', s)}</span>)}
        </div>
      ) : null}
      <div className="row" style={{ border: '1px solid var(--line)', borderRadius: 10, padding: 12 }}>
        <Avatar name={job.technician_name ?? ''} />
        <div className="spacer">
          <strong>Suggested: {techId ? freeTechs.find((d) => d.technician.id === techId)?.technician.name : job.technician_name}</strong>
          <p className="small muted">Free now · qualified · closest match</p>
        </div>
        <label className="sr-only" htmlFor={`reassign-${job.id}`}>Reassign technician</label>
        <select id={`reassign-${job.id}`} className="input" style={{ width: 'auto' }} value={techId}
          onChange={(e) => setTechId(e.target.value)}>
          <option value="">Keep suggested tech</option>
          {freeTechs.map((d) => <option key={d.technician.id} value={d.technician.id}>Reassign to {d.technician.name}</option>)}
        </select>
      </div>
      <p className="small muted">You'll receive {money(job.payout_cents)} after the platform fee (based on the estimate; final price set on site).</p>
      <ErrorAlert message={accept.error ?? decline.error} />
      <div className="row" style={{ justifyContent: 'flex-end' }}>
        <Button busy={decline.busy} onClick={() => decline.run()}>Decline</Button>
        <Button variant="primary" icon="truck" busy={accept.busy} onClick={() => accept.run()}>Accept & dispatch</Button>
      </div>
    </section>
  );
}

function ActiveJobCard({ job, onChanged }: { job: Job; onChanged: () => void }) {
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
            <strong>{job.technician_name}</strong>
            <p className="small muted">{job.customer_first_name ?? 'Customer'} · {job.address ?? job.area_label}</p>
          </div>
        </div>
        <span className={`badge ${job.status === 'completed' ? 'success' : job.status === 'quoted' ? 'amber' : 'primary'}`}>
          {STATUS_LABEL[job.status]}
        </span>
      </div>
      <JobSummary job={job} />
      {job.customer_phone ? (
        <p className="row small"><Icon name="phone" size={14} /> <a href={`tel:${job.customer_phone}`}>{job.customer_phone}</a></p>
      ) : null}

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
          <Button variant="primary" icon="check" busy={act.busy} onClick={() => act.run(() => api.complete(job.id))}>Mark complete & charge</Button>
        </div>
      ) : null}
      {job.status === 'completed' ? (
        <p className="small"><strong>Charged {money(job.payment.captured_cents)}</strong> · you receive {money(job.payout_cents)}</p>
      ) : null}
      <ErrorAlert message={act.error} />
    </section>
  );
}

export function JobsPage() {
  const offers = useLiveData(() => api.jobs(['offered']), 4000);
  const active = useLiveData(() => api.jobs(['dispatched', 'en_route', 'on_site', 'quoted', 'in_progress']), 4000);
  const done = useLiveData(() => api.jobs(['completed']), 10000);
  const reloadAll = () => { void offers.reload(); void active.reload(); void done.reload(); };

  return (
    <>
      <h1>Jobs</h1>
      <ErrorAlert message={offers.error ?? active.error} />
      {offers.data?.map((j) => <OfferCard key={j.id} job={j} onChanged={reloadAll} />)}
      <h2>Active</h2>
      {active.data?.length ? active.data.map((j) => <ActiveJobCard key={j.id} job={j} onChanged={reloadAll} />)
        : <div className="card"><Empty icon="jobs">No active jobs. New offers appear here automatically.</Empty></div>}
      <h2>Completed</h2>
      {done.data?.length ? (
        <div className="card table-wrap">
          <table className="table">
            <thead><tr><th>Date</th><th>Technician</th><th>Work</th><th>Charged</th><th>Your payout</th></tr></thead>
            <tbody>
              {done.data.map((j) => (
                <tr key={j.id}>
                  <td>{new Date(j.created_at).toLocaleDateString()}</td>
                  <td>{j.technician_name}</td>
                  <td>{j.diagnosis?.primary_issue_label ?? 'Service'}</td>
                  <td>{money(j.payment.captured_cents)}</td>
                  <td><strong>{money(j.payout_cents)}</strong></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <p className="muted">No completed jobs yet.</p>}
    </>
  );
}

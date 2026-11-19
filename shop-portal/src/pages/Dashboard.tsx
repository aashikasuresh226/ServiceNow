import { Link } from 'react-router-dom';

import { Icon } from '../components/Icon';
import { Stat } from '../components/ui';
import { api } from '../lib/api';
import { useLiveData, usePortal } from '../lib/hooks';
import { OfferCard } from './Jobs';

export function DashboardPage() {
  const { options } = usePortal();
  const paymentsOn = options?.features.payments ?? false;
  const stats = useLiveData(() => api.dashboard(), 4000);
  const offers = useLiveData(() => api.jobs(['offered']), 4000);

  const readiness = useLiveData(() => api.readiness(), 15000);
  const r = readiness.data;

  return (
    <>
      <div className="row between">
        <h1>Dashboard</h1>
        <span className="small muted">Updates live</span>
      </div>

      {offers.data?.map((job) => <OfferCard key={job.id} job={job} onChanged={() => { void offers.reload(); void stats.reload(); void readiness.reload(); }} />)}

      {r ? (
        <section className={`card ${r.ready ? '' : 'soft'}`} aria-labelledby="ready-title">
          <div className="row between">
            <h2 id="ready-title">{r.ready ? 'Ready for jobs' : 'Not receiving jobs yet'}</h2>
            <span className={`badge ${r.ready ? 'success' : 'amber'}`}>{r.ready ? 'Ready' : 'Action needed'}</span>
          </div>
          <ul className="stack" style={{ margin: 0, paddingLeft: 0, listStyle: 'none' }}>
            {r.checks.map((c) => (
              <li key={c.label} className="row" style={{ alignItems: 'flex-start' }}>
                <span aria-hidden="true" className="stat-icon" style={{ width: 22, height: 22, borderRadius: 11, flexShrink: 0,
                  background: c.ok ? 'var(--primary)' : '#fff', color: c.ok ? '#fff' : 'var(--danger, #b42318)',
                  border: c.ok ? 0 : '1.5px solid currentColor', fontSize: 12, fontWeight: 700 }}>
                  {c.ok ? <Icon name="check" size={13} /> : '!'}
                </span>
                <span>
                  <span className={c.ok ? 'muted' : ''}>{c.label}</span>
                  {!c.ok ? <span className="small muted" style={{ display: 'block' }}>{c.detail}</span> : null}
                </span>
              </li>
            ))}
          </ul>
          {r.technicians.length ? (
            <div className="table-wrap">
              <table>
                <thead><tr><th>Technician</th><th>Next opening</th><th>Problems</th></tr></thead>
                <tbody>
                  {r.technicians.map((t) => (
                    <tr key={t.id}>
                      <td>{t.name}</td>
                      <td>{t.next_opening_label}</td>
                      <td className="small">{t.problems.length ? <Link to="/technicians">{t.problems.join('; ')}</Link> : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          <p className="small muted">
            Homeowners are matched to the qualified technician who can arrive soonest: closest,
            within their service radius, and free now or at their next opening.
            {!paymentsOn ? ' In-app payments are off (no Stripe keys), so customers pay you directly.' : ''}
          </p>
        </section>
      ) : null}

      <div className="grid-stats">
        <Stat icon="user" tone="primary" value={stats.data?.techs_free_now ?? '–'} label="Techs free now" />
        <Stat icon="wrench" tone="amber" value={stats.data?.techs_on_job ?? '–'} label="On a job" />
        <Stat icon="jobs" tone="neutral" value={stats.data?.active_jobs ?? '–'} label="Active jobs" />
        <Stat icon="clock" tone="neutral" value={stats.data?.waitlisted_nearby ?? '–'} label="Homeowners waitlisted" />
      </div>
      <p className="muted small">
        Waitlisted homeowners near you are matched automatically the moment one of your qualified
        technicians frees up.
      </p>
    </>
  );
}

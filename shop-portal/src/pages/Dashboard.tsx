import { Link } from 'react-router-dom';

import { Icon } from '../components/Icon';
import { Stat } from '../components/ui';
import { api } from '../lib/api';
import { useLiveData, usePortal } from '../lib/hooks';
import { OfferCard } from './Jobs';

export function DashboardPage() {
  const { me } = usePortal();
  const shop = me.shop;
  const stats = useLiveData(() => api.dashboard(), 4000);
  const offers = useLiveData(() => api.jobs(['offered']), 4000);
  const techs = useLiveData(() => api.technicians());

  const steps = [
    { done: shop.payouts_enabled, label: 'Set up payouts with Stripe', to: '/settings' },
    { done: !!shop.address, label: 'Add your shop address', to: '/settings' },
    { done: (techs.data ?? []).some((t) => t.is_active), label: 'Add technicians with qualifications & soft skills', to: '/technicians' },
    { done: shop.is_live, label: 'Go live with the switch at the top right', to: '/' },
  ];
  const setupDone = steps.every((s) => s.done);

  return (
    <>
      <div className="row between">
        <h1>Dashboard</h1>
        <span className="small muted">Updates live</span>
      </div>

      {offers.data?.map((job) => <OfferCard key={job.id} job={job} onChanged={() => { void offers.reload(); void stats.reload(); }} />)}

      {!setupDone ? (
        <section className="card soft" aria-labelledby="setup-title">
          <h2 id="setup-title">Finish setting up to receive jobs</h2>
          <ol className="stack" style={{ margin: 0, paddingLeft: 0, listStyle: 'none' }}>
            {steps.map((s, i) => (
              <li key={s.label} className="row">
                <span className="stat-icon" style={{ width: 24, height: 24, borderRadius: 12,
                  background: s.done ? 'var(--primary)' : '#fff', color: s.done ? '#fff' : 'var(--muted)',
                  border: s.done ? 0 : '1.5px solid var(--muted)', fontSize: 12, fontWeight: 700 }}>
                  {s.done ? <Icon name="check" size={14} /> : i + 1}
                </span>
                {s.done ? <span className="muted">{s.label}</span> : <Link to={s.to}>{s.label}</Link>}
              </li>
            ))}
          </ol>
          {shop.scheduling_provider === 'none' ? (
            <p className="small muted">
              Optional: <Link to="/integrations">connect ServiceTitan or Housecall Pro</Link> to sync
              availability automatically. Without it, we use each technician's working hours.
            </p>
          ) : null}
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

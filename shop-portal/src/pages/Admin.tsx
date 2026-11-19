/** The platform admin's page (you, not shops): complaints from every company and every
 * rating and review. Sign in with HVAC_ADMIN_TOKEN from backend/.env. */
import { useEffect, useState } from 'react';

import { Button, Empty, ErrorAlert } from '../components/ui';
import { adminApi, getAdminKey, setAdminKey } from '../lib/api';
import { useAction, useLiveData } from '../lib/hooks';
import type { AdminComplaint } from '../lib/types';

function SignIn({ onDone }: { onDone: () => void }) {
  const [key, setKey] = useState('');
  const go = useAction(async () => {
    await adminApi.check(key.trim());
    setAdminKey(key.trim());
    onDone();
  });
  return (
    <div className="auth-page">
      <form className="card" style={{ width: 'min(420px, 100%)' }}
        onSubmit={(e) => { e.preventDefault(); void go.run(); }}>
        <h1>HVAC Connect admin</h1>
        <p className="muted small">Paste <code>HVAC_ADMIN_TOKEN</code> from <code>backend\.env</code>.</p>
        <label className="field">
          <span>Admin key</span>
          <input className="input" type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} />
        </label>
        <ErrorAlert message={go.error} />
        <Button variant="primary" type="submit" busy={go.busy} disabled={!key.trim()}>Sign in</Button>
      </form>
    </div>
  );
}

function AdminComplaintRow({ c, onChanged }: { c: AdminComplaint; onChanged: () => void }) {
  const [note, setNote] = useState(c.admin_note ?? '');
  const save = useAction(async (status?: 'open' | 'resolved') => {
    await adminApi.updateComplaint(c.id, note, status);
    onChanged();
  });
  return (
    <section className="card">
      <div className="row between">
        <div className="stack" style={{ gap: 2 }}>
          <strong>{c.category_label} · {c.technician_name ?? 'Technician'} ({c.shop_name})</strong>
          <span className="small muted">
            {c.customer_name ?? 'Customer'} · job of {new Date(c.job_date).toLocaleDateString()} · reported {new Date(c.created_at).toLocaleString()}
          </span>
        </div>
        <span className={`badge ${c.status === 'resolved' ? 'success' : 'amber'}`}>
          {c.status === 'resolved' ? `Resolved by ${c.resolved_by === 'admin' ? 'you' : 'the company'}` : 'Open'}
        </span>
      </div>
      <p style={{ margin: 0, whiteSpace: 'pre-wrap' }}>“{c.details}”</p>
      {c.shop_response ? <p className="small" style={{ margin: 0 }}><strong>Company's reply:</strong> {c.shop_response}</p>
        : <p className="small muted" style={{ margin: 0 }}>The company hasn't replied yet.</p>}
      <label className="field">
        <span className="small"><strong>Private note</strong> (only admins see it)</span>
        <textarea className="input" value={note} maxLength={2000} onChange={(e) => setNote(e.target.value)} />
      </label>
      <div className="row" style={{ gap: 8 }}>
        <Button size="small" busy={save.busy} disabled={note === (c.admin_note ?? '')} onClick={() => save.run()}>Save note</Button>
        {c.status === 'open'
          ? <Button size="small" variant="primary" busy={save.busy} onClick={() => save.run('resolved')}>Mark resolved</Button>
          : <Button size="small" busy={save.busy} onClick={() => save.run('open')}>Reopen</Button>}
      </div>
      <ErrorAlert message={save.error} />
    </section>
  );
}

function Dashboard({ onSignOut }: { onSignOut: () => void }) {
  const [tab, setTab] = useState<'complaints' | 'reviews'>('complaints');
  const complaints = useLiveData(() => adminApi.complaints(), 15000);
  const reviews = useLiveData(() => adminApi.reviews(), 30000);
  const error = complaints.error ?? reviews.error;
  useEffect(() => {
    if (error && /admin key/i.test(error)) onSignOut();
  }, [error, onSignOut]);
  const open = complaints.data?.filter((c) => c.status === 'open').length ?? 0;
  return (
    <main className="content" style={{ margin: '0 auto' }}>
      <div className="row between">
        <h1>HVAC Connect admin</h1>
        <Button size="small" onClick={() => { setAdminKey(null); onSignOut(); }}>Sign out</Button>
      </div>
      <div className="tabs" role="tablist">
        <button type="button" role="tab" className="tab" aria-selected={tab === 'complaints'} onClick={() => setTab('complaints')}>
          Complaints{open ? ` (${open} open)` : ''}
        </button>
        <button type="button" role="tab" className="tab" aria-selected={tab === 'reviews'} onClick={() => setTab('reviews')}>
          Ratings & reviews
        </button>
      </div>
      <ErrorAlert message={error} />
      {tab === 'complaints' ? (
        complaints.data?.length
          ? complaints.data.map((c) => <AdminComplaintRow key={c.id} c={c} onChanged={() => void complaints.reload()} />)
          : complaints.data ? <div className="card"><Empty icon="check">No complaints yet.</Empty></div> : null
      ) : reviews.data?.length ? (
        <div className="card table-wrap">
          <table className="table">
            <thead><tr><th>Date</th><th>Company</th><th>Technician</th><th>Tech</th><th>Company</th><th>Review</th></tr></thead>
            <tbody>
              {reviews.data.map((r) => (
                <tr key={r.request_id}>
                  <td>{r.completed_at ? new Date(r.completed_at).toLocaleDateString() : '—'}</td>
                  <td>{r.shop_name ?? '—'}</td>
                  <td>{r.technician_name ?? '—'}</td>
                  <td>{r.technician_rating ? `★ ${r.technician_rating}` : '—'}</td>
                  <td>{r.shop_rating ? `★ ${r.shop_rating}` : '—'}</td>
                  <td className="small">{r.review ?? <span className="muted">—</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : reviews.data ? <div className="card"><Empty icon="users">No ratings yet.</Empty></div> : null}
    </main>
  );
}

export function AdminPage() {
  const [signedIn, setSignedIn] = useState(() => !!getAdminKey());
  return signedIn ? <Dashboard onSignOut={() => setSignedIn(false)} /> : <SignIn onDone={() => setSignedIn(true)} />;
}

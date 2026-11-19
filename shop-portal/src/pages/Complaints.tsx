/** Homeowners' complaints about your technicians. Technicians never see these; the
 * HVAC Connect team does. Your reply is shown to the homeowner in the app. */
import { useState } from 'react';

import { Button, Empty, ErrorAlert } from '../components/ui';
import { api } from '../lib/api';
import { useAction, useLiveData } from '../lib/hooks';
import type { ShopComplaint } from '../lib/types';

function ComplaintCard({ c, onChanged }: { c: ShopComplaint; onChanged: () => void }) {
  const [reply, setReply] = useState(c.shop_response ?? '');
  const save = useAction(async (resolved: boolean) => {
    await api.respondComplaint(c.id, reply, resolved);
    onChanged();
  });
  const changed = reply.trim() !== (c.shop_response ?? '');
  return (
    <section className="card" aria-label={`Complaint about ${c.technician_name ?? 'a technician'}`}>
      <div className="row between">
        <div className="stack" style={{ gap: 2 }}>
          <strong>{c.category_label}</strong>
          <span className="small muted">
            {c.technician_name ?? 'Technician'} · {c.customer_name ?? 'Customer'} · job of {new Date(c.job_date).toLocaleDateString()}
            {c.issue ? ` · ${c.issue}` : ''} · reported {new Date(c.created_at).toLocaleString()}
          </span>
        </div>
        <span className={`badge ${c.status === 'resolved' ? 'success' : 'amber'}`}>
          {c.status === 'resolved' ? `Resolved${c.resolved_by === 'admin' ? ' by HVAC Connect' : ''}` : 'Open'}
        </span>
      </div>
      <p style={{ margin: 0, whiteSpace: 'pre-wrap' }}>“{c.details}”</p>
      <label className="field">
        <span className="small"><strong>Your reply to the customer</strong> (they see it in the app)</span>
        <textarea className="input" value={reply} maxLength={2000} onChange={(e) => setReply(e.target.value)}
          placeholder="Apologize, explain what you'll do (refund, a revisit, coaching the technician)…" />
      </label>
      <div className="row" style={{ gap: 8 }}>
        <Button size="small" disabled={!changed} busy={save.busy} onClick={() => save.run(false)}>Send reply</Button>
        {c.status === 'open' ? (
          <Button size="small" variant="primary" busy={save.busy} onClick={() => save.run(true)}>
            {changed ? 'Send reply & mark resolved' : 'Mark resolved'}
          </Button>
        ) : null}
        {c.shop_responded_at ? <span className="small muted">Replied {new Date(c.shop_responded_at).toLocaleString()}</span> : null}
      </div>
      <ErrorAlert message={save.error} />
    </section>
  );
}

export function ComplaintsPage() {
  const list = useLiveData(() => api.complaints(), 15000);
  const open = list.data?.filter((c) => c.status === 'open') ?? [];
  const resolved = list.data?.filter((c) => c.status === 'resolved') ?? [];
  const reload = () => { void list.reload(); };
  return (
    <>
      <h1>Complaints</h1>
      <p className="muted">
        When a homeowner reports a problem with one of your technicians, it shows here and goes to the HVAC Connect
        team. The technician doesn't see it. Ratings stay private too: you see only your averages.
      </p>
      <ErrorAlert message={list.error} />
      {list.data && !list.data.length ? (
        <div className="card"><Empty icon="check">No complaints. Nice work.</Empty></div>
      ) : null}
      {open.length ? <h2>Open ({open.length})</h2> : null}
      {open.map((c) => <ComplaintCard key={c.id} c={c} onChanged={reload} />)}
      {resolved.length ? <h2>Resolved</h2> : null}
      {resolved.map((c) => <ComplaintCard key={c.id} c={c} onChanged={reload} />)}
    </>
  );
}

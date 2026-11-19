/**
 * How this shop takes jobs: who picks the technician, instant book, and the optional
 * Housecall Pro connection (jobs go into Housecall Pro; its dispatcher assigns the tech).
 * Shops without any software run entirely on this portal and the technician app.
 */
import { useState } from 'react';
import { Link } from 'react-router-dom';

import { Icon } from '../components/Icon';
import { Button, ErrorAlert, Switch } from '../components/ui';
import { api } from '../lib/api';
import { useAction, usePortal } from '../lib/hooks';
import type { DispatchMode } from '../lib/types';

const MODES: { value: DispatchMode; title: string; text: string }[] = [
  {
    value: 'platform',
    title: 'HVAC Connect picks the technician',
    text: 'We send each job to the qualified tech who can arrive soonest (their app shows the offer if they may accept jobs). Fastest for customers.',
  },
  {
    value: 'office',
    title: 'My office picks the technician',
    text: 'You accept the job in Jobs and choose who goes from a list sorted by soonest arrival. Customers see your company until you choose.',
  },
  {
    value: 'software',
    title: "Housecall Pro's dispatcher assigns the technician",
    text: 'Accepted jobs are created in your Housecall Pro schedule (with photos and the AI notes); assign the tech there as usual. We update the customer when you do.',
  },
];

export function IntegrationsPage() {
  const { me, setMe } = usePortal();
  const shop = me?.shop;
  const [apiKey, setApiKey] = useState('');
  const [copied, setCopied] = useState(false);
  const [imported, setImported] = useState<number | null>(null);
  const [limit, setLimit] = useState(String(shop?.instant_book_daily_limit ?? 3));
  const save = useAction(async (data: Parameters<typeof api.setDispatch>[0]) => setMe(await api.setDispatch(data)));
  const connect = useAction(async () => {
    const { count } = await api.connectScheduling('housecall_pro', { api_key: apiKey.trim() }, true);
    setApiKey('');
    setImported(count);
    setMe(await api.me());
  });
  const disconnect = useAction(async () => {
    await api.disconnectScheduling();
    setMe(await api.me());
  });
  const sync = useAction(async () => {
    await api.syncNow();
    setMe(await api.me());
  });
  if (!shop) return null;
  const hcp = shop.scheduling_provider === 'housecall_pro';

  return (
    <>
      <h1>How you take jobs</h1>
      <p className="muted">No software needed: shops can run entirely on this portal and the technician app.
        Connect Housecall Pro if you'd rather keep dispatching there.</p>

      <section className="card stack">
        <h2>Who picks the technician?</h2>
        <div className="stack" role="radiogroup" aria-label="Who picks the technician" style={{ gap: 10 }}>
          {MODES.map((m) => {
            const disabled = m.value === 'software' && !hcp;
            return (
              <label key={m.value} className={`choice ${shop.dispatch_mode === m.value ? 'selected' : ''}`}
                style={{ opacity: disabled ? 0.6 : 1 }}>
                <input type="radio" name="dispatch" checked={shop.dispatch_mode === m.value} disabled={disabled || save.busy}
                  onChange={() => void save.run({ dispatch_mode: m.value })} />
                <span>
                  <strong>{m.title}</strong><br />
                  <span className="small muted">{m.text}</span>
                  {disabled ? <><br /><span className="small">Connect Housecall Pro below first.</span></> : null}
                </span>
              </label>
            );
          })}
        </div>
      </section>

      <section className="card stack">
        <div className="row between">
          <h2>Instant book</h2>
          <Switch checked={shop.instant_book} label="Instant book" disabled={save.busy}
            onChange={(v) => void save.run({ instant_book: v })} />
        </div>
        <p className="small muted">
          Jobs that fit your technicians' skills, service area and hours are accepted automatically, so the customer
          is confirmed in seconds and you get priority over shops that accept by hand. Busy times and time off are respected.
        </p>
        <div className="row" style={{ alignItems: 'flex-end' }}>
          <div className="field" style={{ maxWidth: 220 }}>
            <label htmlFor="ib-limit">Most instant bookings per day</label>
            <input id="ib-limit" className="input" type="number" min={1} max={50} value={limit}
              onChange={(e) => setLimit(e.target.value)} />
          </div>
          <Button busy={save.busy} disabled={Number(limit) === shop.instant_book_daily_limit || !(Number(limit) >= 1)}
            onClick={() => void save.run({ instant_book_daily_limit: Number(limit) })}>Save limit</Button>
        </div>
      </section>
      <ErrorAlert message={save.error} />

      <div className="grid-2">
        <section className="card stack">
          <div className="row between">
            <h2>Housecall Pro</h2>
            {hcp ? <span className="badge success">Connected</span> : <span className="badge neutral">Optional</span>}
          </div>
          {hcp ? (
            <>
              <p className="small muted">
                Every minute we copy your Housecall Pro jobs (including new customers): assigned technicians see them in
                the technician app, they show under <Link to="/jobs">Jobs</Link>, and your customers appear under{' '}
                <Link to="/customers">Customers</Link> to invite. When you accept a job from us,
                it's created in Housecall Pro{shop.dispatch_mode === 'software' ? ' for your dispatcher to assign' : ''}.
                Link each technician to their Housecall Pro employee on <Link to="/technicians">Technicians</Link> (matched
                by name automatically).
              </p>
              {imported != null ? <p className="notice small" role="status">Connected. Added {imported} technician(s) from Housecall Pro.</p> : null}
              <p className="small">
                Last checked: {shop.scheduling_last_synced_at ? new Date(shop.scheduling_last_synced_at).toLocaleString() : 'not yet'}
              </p>
              {shop.scheduling_last_error ? <p className="notice small" role="alert">{shop.scheduling_last_error}</p> : null}
              {shop.scheduling_webhook_url ? (
                <div className="field">
                  <label htmlFor="hook">Webhook URL (optional, for instant updates)</label>
                  <div className="row" style={{ flexWrap: 'nowrap' }}>
                    <input id="hook" className="input" readOnly value={shop.scheduling_webhook_url}
                      onFocus={(e) => e.currentTarget.select()} />
                    <Button size="small" onClick={() => {
                      void navigator.clipboard?.writeText(shop.scheduling_webhook_url ?? '').then(() => setCopied(true));
                    }}>{copied ? 'Copied' : 'Copy'}</Button>
                  </div>
                  <span className="small muted">In Housecall Pro: App Store → Webhooks → paste this URL and turn on job
                    events. Must be a public https address (not localhost). Without it we still check every minute.</span>
                </div>
              ) : null}
              <div className="row">
                <Button icon="refresh" busy={sync.busy} onClick={() => void sync.run()}>Sync now</Button>
                <Button variant="danger" busy={disconnect.busy}
                  onClick={() => { if (window.confirm('Disconnect Housecall Pro? Jobs already sent stay in Housecall Pro.')) void disconnect.run(); }}>
                  Disconnect
                </Button>
              </div>
              <ErrorAlert message={sync.error ?? disconnect.error} />
            </>
          ) : (
            <form className="stack" onSubmit={(e) => { e.preventDefault(); void connect.run(); }}>
              <ol className="small muted" style={{ margin: 0, paddingLeft: 18 }}>
                <li>Housecall Pro needs the <strong>MAX</strong> plan for API access.</li>
                <li>In Housecall Pro: <strong>App Store → API</strong> → generate an API key.</li>
                <li>Paste it here. It's stored encrypted and never shown again.</li>
              </ol>
              <div className="field">
                <label htmlFor="hcp-key">Housecall Pro API key</label>
                <input id="hcp-key" className="input" type="password" autoComplete="off" value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)} required minLength={8} />
              </div>
              <ErrorAlert message={connect.error} />

              <div><Button type="submit" variant="primary" icon="plug" busy={connect.busy}>Connect Housecall Pro</Button></div>
            </form>
          )}
        </section>
        <section className="card stack">
          <div className="row between">
            <h2>ServiceTitan</h2>
            <span className="badge amber">Coming soon</span>
          </div>
          <p className="small muted">Sync technicians, shifts and booked jobs from ServiceTitan Dispatch.</p>
          <p className="small"><Icon name="info" size={14} /> Until then, ServiceTitan shops can use this portal with their technicians' working hours.</p>
        </section>
      </div>
    </>
  );
}

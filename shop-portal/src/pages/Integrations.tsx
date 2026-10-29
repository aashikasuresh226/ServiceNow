import { useState } from 'react';

import { Icon } from '../components/Icon';
import { Button, ErrorAlert, Switch } from '../components/ui';
import { api } from '../lib/api';
import { clock, useAction, usePortal } from '../lib/hooks';

const PROVIDERS = {
  servicetitan: {
    name: 'ServiceTitan',
    fields: [
      ['tenant_id', 'Tenant ID'],
      ['client_id', 'Client ID'],
      ['client_secret', 'Client secret'],
      ['app_key', 'App key'],
    ],
    help: 'Create an app in the ServiceTitan Developer Portal with read access to Settings, Dispatch and JPM.',
  },
  housecall_pro: {
    name: 'Housecall Pro',
    fields: [['api_key', 'API key']],
    help: 'Requires the MAX plan. An admin can generate an API key under App Store → API.',
  },
} as const;

type Provider = keyof typeof PROVIDERS;

export function IntegrationsPage() {
  const { me, setMe } = usePortal();
  const shop = me.shop;
  const [provider, setProvider] = useState<Provider>('servicetitan');
  const [creds, setCreds] = useState<Record<string, string>>({});
  const [writeBack, setWriteBack] = useState(true);
  const [message, setMessage] = useState<string | null>(null);

  const connect = useAction(async () => {
    const { count } = await api.connectScheduling(provider, creds, writeBack);
    setMe(await api.me());
    setMessage(`Connected. Imported ${count} technician${count === 1 ? '' : 's'}; review them on the Technicians page.`);
  });
  const sync = useAction(async () => {
    const { count } = await api.syncNow();
    setMe(await api.me());
    setMessage(`Synced ${count} schedule blocks.`);
  });
  const disconnect = useAction(async () => { await api.disconnectScheduling(); setMe(await api.me()); });

  if (shop.scheduling_provider !== 'none') {
    const p = PROVIDERS[shop.scheduling_provider];
    return (
      <>
        <h1>Scheduling software</h1>
        <section className="card">
          <div className="row between">
            <h2>{p.name}</h2>
            <span className="badge success"><Icon name="check" size={13} /> Connected</span>
          </div>
          <p className="muted">
            We read your technicians, booked jobs, shifts and time off to know who is free right now.
            {shop.scheduling_last_synced_at ? ` Last synced at ${clock(shop.scheduling_last_synced_at)}.` : ''}
          </p>
          {shop.scheduling_last_error ? <ErrorAlert message={`Last sync failed: ${shop.scheduling_last_error}`} /> : null}
          {message ? <p className="notice small">{message}</p> : null}
          <ErrorAlert message={sync.error ?? disconnect.error} />
          <div className="row">
            <Button icon="refresh" busy={sync.busy} onClick={() => sync.run()}>Sync now</Button>
            <Button variant="danger" busy={disconnect.busy} onClick={() => disconnect.run()}>Disconnect</Button>
          </div>
        </section>
      </>
    );
  }

  const spec = PROVIDERS[provider];
  return (
    <>
      <h1>Scheduling software</h1>
      <p className="muted">Connect your field-service software so we know which technicians are free, in real time.
        Without it, we use each technician's working hours.</p>
      <div className="grid-2">
        {(Object.keys(PROVIDERS) as Provider[]).map((key) => (
          <button key={key} type="button" className="card" onClick={() => { setProvider(key); setCreds({}); }}
            aria-pressed={provider === key}
            style={{ textAlign: 'left', cursor: 'pointer', borderColor: provider === key ? 'var(--primary)' : undefined, borderWidth: provider === key ? 2 : 1 }}>
            <strong>{PROVIDERS[key].name}</strong>
            <span className="small muted">{PROVIDERS[key].help}</span>
          </button>
        ))}
      </div>
      <form className="card" onSubmit={(e) => { e.preventDefault(); void connect.run(); }}>
        <h2>Connect {spec.name}</h2>
        <div className="grid-2">
          {spec.fields.map(([key, name]) => (
            <div key={key} className="field">
              <label htmlFor={key}>{name}</label>
              <input id={key} className="input" required autoComplete="off"
                type={key.includes('secret') || key.includes('key') ? 'password' : 'text'}
                value={creds[key] ?? ''} onChange={(e) => setCreds({ ...creds, [key]: e.target.value })} />
            </div>
          ))}
        </div>
        <div className="row">
          <Switch checked={writeBack} onChange={setWriteBack} label="Write accepted jobs back to my calendar" />
          <span>Write accepted jobs back to my calendar</span>
        </div>
        <p className="small muted"><Icon name="shield" size={13} /> Credentials are encrypted and never shown again.</p>
        <ErrorAlert message={connect.error} />
        <div><Button type="submit" variant="primary" busy={connect.busy}>Connect & import technicians</Button></div>
      </form>
    </>
  );
}

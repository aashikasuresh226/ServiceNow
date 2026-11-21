import { useRef, useState } from 'react';
import type { FormEvent } from 'react';

import { Icon } from '../components/Icon';
import { PasswordInput } from '../components/PasswordInput';
import { Button, ErrorAlert } from '../components/ui';
import { api } from '../lib/api';
import { useAction, usePortal } from '../lib/hooks';
import { PasswordChecklist } from './Auth';
import { PayoutsCard } from './Payouts';

export function SettingsPage() {
  const { me, setMe } = usePortal();
  const shop = me.shop;
  const [name, setName] = useState(shop.name);
  const [phone, setPhone] = useState(shop.phone ?? '');
  const [address, setAddress] = useState(shop.address ?? '');
  const [saved, setSaved] = useState(false);
  const save = useAction(async () => {
    setMe(await api.updateShop({ name, phone, ...(address !== shop.address ? { address } : {}) }));
    setSaved(true);
  });

  return (
    <>
      <h1>Shop & payouts</h1>
      <div className="grid-2" style={{ alignItems: 'start' }}>
        <form className="card" onSubmit={(e) => { e.preventDefault(); setSaved(false); void save.run(); }}>
          <h2>Shop profile</h2>
          <LogoField />
          <div className="field">
            <label htmlFor="shop-name">Shop name</label>
            <input id="shop-name" className="input" value={name} onChange={(e) => setName(e.target.value)} required />
          </div>
          <div className="field">
            <label htmlFor="shop-phone">Phone (shown to booked homeowners)</label>
            <input id="shop-phone" className="input" value={phone} onChange={(e) => setPhone(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="shop-address">Shop address</label>
            <input id="shop-address" className="input" value={address} onChange={(e) => setAddress(e.target.value)}
              placeholder="123 Main St, Atlanta, GA 30303" />
            <span className="small muted">Include street number, city, state and ZIP. We look it up
              to find your location; technicians are matched by distance from here.</span>
          </div>
          <ErrorAlert message={save.error} />
          <div className="row">
            <Button type="submit" variant="primary" busy={save.busy}>Save</Button>
            {saved ? <span className="small" style={{ color: 'var(--success)' }}>Saved</span> : null}
          </div>
        </form>
        <div className="stack">
          <AccountCard />
          <PasswordCard />
        </div>
      </div>
      <div className="grid-2" style={{ alignItems: 'start' }}>
        <PayoutsCard />
      </div>
    </>
  );
}

/** Shop logo: customers see it with their technician. */
function LogoField() {
  const { me, setMe } = usePortal();
  const input = useRef<HTMLInputElement>(null);
  const upload = useAction(async (file: File) => setMe(await api.uploadLogo(file)));
  const remove = useAction(async () => setMe(await api.removeLogo()));
  const logo = me.shop.logo_url;
  return (
    <div className="field">
      <span className="label">Logo</span>
      <div className="row" style={{ gap: 14 }}>
        <div className="logo-preview">
          {logo ? <img src={logo} alt={`${me.shop.name} logo`} /> : <Icon name="building" size={26} />}
        </div>
        <div className="stack" style={{ gap: 6 }}>
          <div className="row">
            <Button type="button" busy={upload.busy} icon="plus" onClick={() => input.current?.click()}>
              {logo ? 'Replace logo' : 'Upload logo'}
            </Button>
            {logo ? <Button type="button" variant="danger" busy={remove.busy} onClick={() => remove.run()}>Remove</Button> : null}
          </div>
          <span className="small muted">PNG or JPG, square works best. Shown to customers with their technician.</span>
        </div>
      </div>
      <input ref={input} type="file" accept="image/png,image/jpeg,image/webp" hidden
        onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload.run(f); e.target.value = ''; }} />
      <ErrorAlert message={upload.error ?? remove.error} />
    </div>
  );
}

/** The signed-in person's own details. */
function AccountCard() {
  const { me, setMe } = usePortal();
  const [name, setName] = useState(me.user_name ?? '');
  const [saved, setSaved] = useState(false);
  const save = useAction(async () => { setMe(await api.updateAccount(name)); setSaved(true); });
  return (
    <form className="card" onSubmit={(e) => { e.preventDefault(); setSaved(false); void save.run(); }}>
      <h2>Your account</h2>
      <div className="field">
        <label htmlFor="user-name">Your name</label>
        <input id="user-name" className="input" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
      </div>
      <div className="field">
        <span className="label">Sign-in email</span>
        <span>{me.user_email}</span>
      </div>
      <p className="small muted row" style={{ margin: 0 }}><Icon name="shield" size={14} /> 2-step verification is on for this account.</p>
      <ErrorAlert message={save.error} />
      <div className="row">
        <Button type="submit" busy={save.busy}>Save</Button>
        {saved ? <span className="small" style={{ color: 'var(--success)' }}>Saved</span> : null}
      </div>
    </form>
  );
}

function PasswordCard() {
  const { me, setMe } = usePortal();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [done, setDone] = useState(false);
  const change = useAction(async () => {
    await api.changePassword(me.has_password ? current : null, next);
    setMe({ ...me, has_password: true });
    setCurrent(''); setNext(''); setDone(true);
  });
  const onSubmit = (e: FormEvent) => { e.preventDefault(); setDone(false); void change.run(); };
  return (
    <form className="card" onSubmit={onSubmit}>
      <h2>{me.has_password ? 'Change password' : 'Set a password'}</h2>
      {!me.has_password ? <p className="small muted" style={{ margin: 0 }}>You sign in with Google. Add a password to also sign in with your email.</p> : null}
      {me.has_password ? (
        <div className="field">
          <label htmlFor="current-password">Current password</label>
          <PasswordInput id="current-password" autoComplete="current-password" required value={current}
            onChange={(e) => setCurrent(e.target.value)} />
        </div>
      ) : null}
      <div className="field">
        <label htmlFor="new-password">New password</label>
        <PasswordInput id="new-password" autoComplete="new-password" required minLength={8} value={next}
          onChange={(e) => setNext(e.target.value)} />
        <PasswordChecklist password={next} />
      </div>
      <ErrorAlert message={change.error} />
      <div className="row">
        <Button type="submit" busy={change.busy}>{me.has_password ? 'Change password' : 'Set password'}</Button>
        {done ? <span className="small" style={{ color: 'var(--success)' }}>Password changed. Other devices were signed out.</span> : null}
      </div>
    </form>
  );
}

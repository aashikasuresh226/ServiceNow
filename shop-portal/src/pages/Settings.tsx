import { useState } from 'react';

import { Button, ErrorAlert } from '../components/ui';
import { api } from '../lib/api';
import { useAction, usePortal } from '../lib/hooks';
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
              placeholder="Street, city, ZIP" />
            <span className="small muted">Technicians are matched by distance from here.</span>
          </div>
          <ErrorAlert message={save.error} />
          <div className="row">
            <Button type="submit" variant="primary" busy={save.busy}>Save</Button>
            {saved ? <span className="small" style={{ color: 'var(--success)' }}>Saved</span> : null}
          </div>
        </form>
        <PayoutsCard />
      </div>
    </>
  );
}

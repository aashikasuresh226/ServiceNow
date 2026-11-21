import { useEffect, useState } from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';

import { api, onSignOut, setTokens } from '../lib/api';
import { PortalContext, useAction, useLiveData, useOptions } from '../lib/hooks';
import type { ShopMe } from '../lib/types';
import { Icon } from './Icon';
import { Logo } from './Logo';
import { ErrorAlert, Switch } from './ui';

const NAV = [
  { to: '/', icon: 'dashboard', label: 'Dashboard', end: true },
  { to: '/jobs', icon: 'jobs', label: 'Jobs' },
  { to: '/technicians', icon: 'users', label: 'Technicians' },
  { to: '/customers', icon: 'user', label: 'Customers' },
  { to: '/complaints', icon: 'alert', label: 'Complaints' },
  { to: '/availability', icon: 'calendar', label: 'Availability' },
  { to: '/integrations', icon: 'plug', label: 'How you take jobs' },
  { to: '/settings', icon: 'settings', label: 'Shop & payouts' },
];

export function Layout() {
  const navigate = useNavigate();
  const options = useOptions();
  const [me, setMe] = useState<ShopMe | null>(null);
  const { data: offers } = useLiveData(() => api.jobs(['offered']), 4000);
  const { data: complaints } = useLiveData(() => api.complaints(), 30000);
  const openComplaints = complaints?.filter((c) => c.status === 'open').length ?? 0;

  useEffect(() => {
    onSignOut(() => navigate('/login', { replace: true }));
    api.me().then(setMe).catch(() => navigate('/login', { replace: true }));
  }, [navigate]);

  const live = useAction(async (value: boolean) => setMe(await api.setLive(value)));

  if (!me) return <div className="empty">Loading…</div>;
  const shop = me.shop;
  return (
    <PortalContext.Provider value={{ me, setMe, options }}>
      <div className="app">
        <nav className="sidebar" aria-label="Main">
          <div className="brand">
            {shop.logo_url ? <img className="brand-logo" src={shop.logo_url} alt="" /> : <Logo size={30} />}
            {shop.name}
          </div>
          {NAV.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end}
              className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
              <Icon name={item.icon} />
              {item.label}
              {'optional' in item ? <span className="small muted" style={{ marginLeft: 'auto' }}>Optional</span> : null}
              {item.to === '/complaints' && openComplaints ? (
                <span className="nav-count" aria-label={`${openComplaints} open complaints`}>{openComplaints}</span>
              ) : null}
              {item.to === '/jobs' && offers?.length ? (
                <span className="nav-count" aria-label={`${offers.length} new offers`}>{offers.length}</span>
              ) : null}
            </NavLink>
          ))}
          <div className="sidebar-footer">
            <span className="small muted">{me.user_email}</span>
            <button type="button" className="nav-link" style={{ border: 0, background: 'none', cursor: 'pointer', padding: '6px 0' }}
              onClick={async () => { await api.logout(); setTokens(null); }}>
              <Icon name="logout" /> Sign out
            </button>
          </div>
        </nav>
        <div className="main">
          <header className="topbar">
            <span className="spacer" />
            <span className="small muted">Accept on-demand requests</span>
            <Switch checked={shop.is_live} label="Accept on-demand requests" disabled={live.busy}
              onChange={(v) => live.run(v)} />
          </header>
          <main className="content">
            <ErrorAlert message={live.error} />
            <Outlet />
          </main>
        </div>
      </div>
    </PortalContext.Provider>
  );
}

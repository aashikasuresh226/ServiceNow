/** Stripe Connect payouts: shown during sign-up and from Settings. */
import { useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';

import { Icon } from '../components/Icon';
import { Button, ErrorAlert } from '../components/ui';
import { api } from '../lib/api';
import { useAction, usePortal } from '../lib/hooks';

const SCHEDULES = [
  { value: 'daily', title: 'Daily', hint: 'Automatic' },
  { value: 'weekly', title: 'Weekly', hint: 'Every Monday' },
  { value: 'manual', title: 'Manual', hint: 'Pay out on request' },
];

export function PayoutFlowDiagram() {
  return (
    <svg viewBox="0 0 478 96" width="100%" role="img" aria-label="Homeowner pays in the app, the platform keeps its fee, the rest is paid out to your bank">
      <rect width="478" height="96" rx="12" fill="#F4F5F7" />
      <circle cx="70" cy="38" r="22" fill="#fff" stroke="#1A1F2B" strokeWidth="2" />
      <rect x="58" y="30" width="24" height="16" rx="3" fill="#E8EEFD" stroke="#1D4ED8" strokeWidth="1.8" />
      <path d="M58 35h24" stroke="#1D4ED8" strokeWidth="2.5" />
      <text x="70" y="80" textAnchor="middle" fontSize="11" fill="#1A1F2B">Homeowner pays in app</text>
      <path d="M110 38h66" stroke="#1D4ED8" strokeWidth="2" strokeDasharray="4 4" />
      <path d="M172 33l6 5-6 5" fill="none" stroke="#1D4ED8" strokeWidth="2" strokeLinecap="round" />
      <circle cx="239" cy="38" r="22" fill="#1D4ED8" />
      <text x="239" y="43" textAnchor="middle" fontSize="13" fontWeight="700" fill="#fff">15%</text>
      <text x="239" y="80" textAnchor="middle" fontSize="11" fill="#1A1F2B">Platform fee</text>
      <path d="M279 38h66" stroke="#1D4ED8" strokeWidth="2" strokeDasharray="4 4" />
      <path d="M341 33l6 5-6 5" fill="none" stroke="#1D4ED8" strokeWidth="2" strokeLinecap="round" />
      <circle cx="408" cy="38" r="22" fill="#fff" stroke="#1A1F2B" strokeWidth="2" />
      <path d="M396 32l12-7 12 7zM397 46h22M400 34v10M408 34v10M416 34v10" fill="none" stroke="#1A1F2B" strokeWidth="2" strokeLinejoin="round" />
      <text x="408" y="80" textAnchor="middle" fontSize="11" fill="#1A1F2B">Payout to your bank</text>
    </svg>
  );
}

export function PayoutsCard({ onboarding = false }: { onboarding?: boolean }) {
  const { me, setMe } = usePortal();
  const shop = me.shop;
  const [params] = useSearchParams();
  const navigate = useNavigate();

  const connect = useAction(async () => {
    const { url } = await api.payoutLink();
    window.location.assign(url);
  });
  const refresh = useAction(async () => setMe(await api.refreshPayouts()));
  const schedule = useAction(async (value: string) => setMe(await api.payoutSchedule(value)));

  useEffect(() => {
    if (params.get('status')) void refresh.run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <section className="card" aria-labelledby="payouts-title">
      <div className="row between">
        <h2 id="payouts-title">Get paid</h2>
        <span className={`badge ${shop.payouts_enabled ? 'success' : 'amber'}`}>
          {shop.payouts_enabled ? 'Payouts active' : 'Not set up'}
        </span>
      </div>
      <PayoutFlowDiagram />
      <div className="field">
        <span className="label">Payout schedule</span>
        <div className="grid-stats" role="radiogroup" aria-label="Payout schedule">
          {SCHEDULES.map((s) => (
            <label key={s.value} className="card" style={{ padding: 12, cursor: 'pointer',
              borderColor: shop.payout_schedule === s.value ? 'var(--primary)' : undefined }}>
              <span className="row">
                <input type="radio" name="schedule" checked={shop.payout_schedule === s.value}
                  onChange={() => schedule.run(s.value)} />
                <strong>{s.title}</strong>
              </span>
              <span className="small muted">{s.hint}</span>
            </label>
          ))}
        </div>
      </div>
      <div className="row" style={{ border: '1px solid var(--line)', borderRadius: 10, padding: 12 }}>
        <span className="stat-icon" style={{ background: '#eef0f3' }}><Icon name="bank" /></span>
        <div className="spacer">
          <strong>Stripe payouts account</strong>
          <p className="small muted">Stripe verifies the owner's ID and bank account. We never see full bank details.</p>
        </div>
      </div>
      <ErrorAlert message={connect.error ?? refresh.error ?? schedule.error} />
      <div className="row">
        {!shop.payouts_enabled ? (
          <Button variant="primary" busy={connect.busy} onClick={() => connect.run()}>Set up payouts with Stripe</Button>
        ) : (
          <Button busy={connect.busy} onClick={() => connect.run()}>Update bank details</Button>
        )}
        {onboarding ? (
          <Button onClick={() => navigate('/', { replace: true })}>
            {shop.payouts_enabled ? 'Continue to dashboard' : 'Do this later'}
          </Button>
        ) : null}
      </div>
    </section>
  );
}

export function PayoutsOnboarding() {
  return (
    <div className="stack" style={{ maxWidth: 640 }}>
      <h1>Set up payouts</h1>
      <p className="muted">Connect a bank account so you can go live and receive jobs.</p>
      <PayoutsCard onboarding />
    </div>
  );
}

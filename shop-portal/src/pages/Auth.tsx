/** Sign in / create account, then the mandatory 2-step verification. */
import QRCode from 'qrcode';
import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';

import { Icon } from '../components/Icon';
import { Button, ErrorAlert } from '../components/ui';
import { api, setTokens } from '../lib/api';
import { useAction, useOptions } from '../lib/hooks';
import type { LoginStep } from '../lib/types';

const DEMO = { email: 'demo@coolbreeze.example.com', password: 'DemoPassword123!' };

function Hero() {
  return (
    <div className="auth-side">
      <svg width="200" height="140" viewBox="0 0 168 120" aria-hidden="true">
        <path d="M8 104H160" stroke="#9AA3B2" strokeWidth="2" strokeLinecap="round" />
        <rect x="12" y="50" width="92" height="46" rx="6" fill="#fff" stroke="#1A1F2B" strokeWidth="2" />
        <path d="M104 62h26l18 18v16h-44z" fill="#fff" stroke="#1A1F2B" strokeWidth="2" strokeLinejoin="round" />
        <path d="M112 66h14l10 12h-24z" fill="#DCE5FB" />
        <rect x="12" y="66" width="92" height="10" fill="#1D4ED8" />
        <circle cx="36" cy="98" r="9" fill="#1A1F2B" /><circle cx="126" cy="98" r="9" fill="#1A1F2B" />
        <circle cx="36" cy="98" r="3" fill="#fff" /><circle cx="126" cy="98" r="3" fill="#fff" />
        <path d="M128 8l22 8v16c0 14-10 22-22 26-12-4-22-12-22-26V16z" fill="#1D4ED8" />
        <path d="M119 32l7 7 12-13" fill="none" stroke="#fff" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <h1 style={{ fontSize: 22 }}>Get jobs from homeowners near you</h1>
      <p className="muted">Fill open time in your schedule with on-demand, pre-diagnosed HVAC jobs.</p>
    </div>
  );
}

export function AuthPage() {
  const navigate = useNavigate();
  const options = useOptions();
  const [mode, setMode] = useState<'login' | 'signup'>('login');
  const [step, setStep] = useState<LoginStep | null>(null);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [shopName, setShopName] = useState('');

  const submit = useAction(async () => {
    setStep(mode === 'login'
      ? await api.login(email, password)
      : await api.signup({ email, password, shop_name: shopName }));
  });
  const onSubmit = (e: FormEvent) => { e.preventDefault(); void submit.run(); };

  if (step?.step === 'mfa') {
    return <MfaVerify step={step} onDone={() => navigate('/', { replace: true })} onBack={() => setStep(null)} />;
  }
  if (step?.step === 'mfa_setup') {
    return <MfaSetup token={step.token} isNew={mode === 'signup'}
      onDone={() => navigate(mode === 'signup' ? '/onboarding/payouts' : '/', { replace: true })} />;
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <Hero />
        <form className="auth-form" onSubmit={onSubmit}>
          <div className="tabs" role="tablist">
            <button type="button" role="tab" className="tab" aria-selected={mode === 'login'} onClick={() => setMode('login')}>Sign in</button>
            <button type="button" role="tab" className="tab" aria-selected={mode === 'signup'} onClick={() => setMode('signup')}>Create account</button>
          </div>
          {mode === 'signup' ? (
            <div className="field">
              <label htmlFor="shop">Shop name</label>
              <input id="shop" className="input" value={shopName} onChange={(e) => setShopName(e.target.value)} required minLength={2} />
            </div>
          ) : null}
          <div className="field">
            <label htmlFor="email">Business email</label>
            <input id="email" className="input" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </div>
          <div className="field">
            <label htmlFor="password">Password</label>
            <input id="password" className="input" type="password" value={password}
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
              onChange={(e) => setPassword(e.target.value)} required minLength={mode === 'signup' ? 12 : 1} />
            {mode === 'signup' ? <span className="small muted">At least 12 characters</span> : null}
          </div>
          <ErrorAlert message={submit.error} />
          <Button type="submit" variant="primary" busy={submit.busy}>
            {mode === 'login' ? 'Sign in' : 'Create account'}
          </Button>
          <p className="row small muted"><Icon name="shield" size={14} color="var(--primary)" /> 2-step verification is required on every shop account</p>
          {options?.demo_mode && mode === 'login' ? (
            <div className="notice small">
              <span><strong>Demo mode.</strong> Sign in as Cool Breeze HVAC.{' '}
                <a href="#demo" onClick={(e) => { e.preventDefault(); setEmail(DEMO.email); setPassword(DEMO.password); }}>Fill demo login</a></span>
            </div>
          ) : null}
        </form>
      </div>
    </div>
  );
}

function CodeForm({ title, subtitle, devCode, submitLabel, onSubmit, error, busy, children }: {
  title: string;
  subtitle: string;
  devCode: string | null;
  submitLabel: string;
  onSubmit: (code: string) => void;
  error: string | null;
  busy: boolean;
  children?: React.ReactNode;
}) {
  const [code, setCode] = useState(devCode ?? '');
  return (
    <div className="auth-page">
      <form className="card" style={{ maxWidth: 440, width: '100%', padding: 28 }}
        onSubmit={(e) => { e.preventDefault(); onSubmit(code); }}>
        <h1>{title}</h1>
        <p className="muted">{subtitle}</p>
        {children}
        <div className="field">
          <label htmlFor="code">6-digit code</label>
          <input id="code" className="input code-input" inputMode="numeric" autoComplete="one-time-code"
            value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))} autoFocus />
        </div>
        {devCode ? <div className="notice small">Demo mode: the current code was filled in for you.</div> : null}
        <ErrorAlert message={error} />
        <Button type="submit" variant="primary" busy={busy} disabled={code.length !== 6}>{submitLabel}</Button>
      </form>
    </div>
  );
}

function MfaVerify({ step, onDone, onBack }: { step: LoginStep; onDone: () => void; onBack: () => void }) {
  const verify = useAction(async (code: string) => {
    setTokens(await api.loginMfa(step.token, code));
    onDone();
  });
  return (
    <CodeForm title="2-step verification" subtitle="Enter the code from your authenticator app."
      devCode={step.dev_code} submitLabel="Verify" onSubmit={(c) => verify.run(c)}
      error={verify.error} busy={verify.busy}>
      <a href="#back" className="small" onClick={(e) => { e.preventDefault(); onBack(); }}>Use a different account</a>
    </CodeForm>
  );
}

function MfaSetup({ token, onDone }: { token: string; isNew: boolean; onDone: () => void }) {
  const [enroll, setEnroll] = useState<{ secret: string; otpauth_uri: string; dev_code: string | null } | null>(null);
  const [qr, setQr] = useState<string | null>(null);
  const start = useAction(async () => {
    const result = await api.enrollMfa(token);
    setEnroll(result);
    setQr(await QRCode.toDataURL(result.otpauth_uri, { margin: 1, width: 180 }));
  });
  const activate = useAction(async (code: string) => {
    setTokens(await api.activateMfa(token, code));
    onDone();
  });
  const started = useRef(false);
  useEffect(() => {
    // Enroll once: a second call would replace the secret the QR code shows.
    if (started.current) return;
    started.current = true;
    void start.run();
  }, [start]);

  if (!enroll) {
    return <div className="auth-page"><div className="card"><ErrorAlert message={start.error} />{start.error ? null : 'Setting up…'}</div></div>;
  }
  return (
    <CodeForm title="Turn on 2-step verification"
      subtitle="Scan this with Google Authenticator, 1Password or a similar app, then enter the code it shows."
      devCode={enroll.dev_code} submitLabel="Turn on & continue" onSubmit={(c) => activate.run(c)}
      error={activate.error} busy={activate.busy}>
      <div className="row" style={{ alignItems: 'center' }}>
        {qr ? <img src={qr} width={150} height={150} alt="QR code for your authenticator app" /> : null}
        <div className="stack small">
          <span className="muted">Can't scan? Enter this key:</span>
          <code style={{ wordBreak: 'break-all', fontWeight: 700 }}>{enroll.secret}</code>
        </div>
      </div>
    </CodeForm>
  );
}

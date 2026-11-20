/**
 * Sign in / create account with Google or email + password. A new email address is
 * proven with a link (sent by Firebase), then the mandatory authenticator-app code
 * (2-step verification) on every shop account.
 */
import QRCode from 'qrcode';
import { useCallback, useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';

import { GoogleButton } from '../components/GoogleButton';
import { Icon } from '../components/Icon';
import { Button, ErrorAlert } from '../components/ui';
import { api, setTokens } from '../lib/api';
import { useAction, useOptions } from '../lib/hooks';
import type { LoginStep } from '../lib/types';

const PASSWORD_RULES: [string, (p: string) => boolean][] = [
  ['At least 8 characters', (p) => p.length >= 8],
  ['A capital letter', (p) => /[A-Z]/.test(p)],
  ['A number', (p) => /\d/.test(p)],
  ['A symbol (like ! # $ %)', (p) => /[^A-Za-z0-9]/.test(p)],
];

export function PasswordChecklist({ password }: { password: string }) {
  return (
    <ul className="checklist small" aria-label="Requirements">
      {PASSWORD_RULES.map(([text, ok]) => {
        const met = ok(password);
        return (
          <li key={text} className={met ? 'met' : ''}>
            <Icon name={met ? 'check' : 'dot'} size={13} />
            {text}
            <span className="sr-only">{met ? ' (done)' : ' (needed)'}</span>
          </li>
        );
      })}
      <li className="muted">Not a common or leaked password (checked when you continue)</li>
    </ul>
  );
}

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
  const [params] = useSearchParams();
  const [mode, setMode] = useState<'login' | 'signup'>(params.get('mode') === 'signup' ? 'signup' : 'login');
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
  const google = useAction(async (idToken: string) => {
    setStep(await api.google(idToken, mode === 'signup' ? shopName.trim() : undefined));
  });
  const getNonce = useCallback(async () => (await api.googleNonce()).nonce, []);
  const googleClientId = options?.features.google_client_id;
  const canUseGoogle = mode === 'login' || shopName.trim().length >= 2;

  if (step?.step === 'verify_email') {
    return <VerifyEmailStep step={step} onNext={setStep} onBack={() => setStep(null)} />;
  }
  if (step?.step === 'mfa') {
    return <MfaVerify step={step} onDone={() => navigate('/', { replace: true })} onBack={() => setStep(null)} />;
  }
  if (step?.step === 'mfa_setup') {
    return <MfaSetup token={step.token} isNew={mode === 'signup'}
      onDone={() => navigate(mode === 'signup' && options?.features.payments ? '/onboarding/payouts' : '/', { replace: true })} />;
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <Hero />
        <form className="auth-form" onSubmit={onSubmit}>
          <Link to="/start" className="small muted">← Not a shop owner?</Link>
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
              onChange={(e) => setPassword(e.target.value)} required minLength={mode === 'signup' ? 8 : 1} />
            {mode === 'signup' ? <PasswordChecklist password={password} /> : null}
          </div>
          <ErrorAlert message={submit.error} />
          <Button type="submit" variant="primary" busy={submit.busy}>
            {mode === 'login' ? 'Sign in' : 'Create account'}
          </Button>
          {googleClientId ? (
            <>
              <div className="row small muted" style={{ gap: 10 }}>
                <span style={{ flex: 1, height: 1, background: 'var(--line)' }} />or<span style={{ flex: 1, height: 1, background: 'var(--line)' }} />
              </div>
              {canUseGoogle ? (
                <GoogleButton key={mode} clientId={googleClientId} getNonce={getNonce}
                  text={mode === 'login' ? 'signin_with' : 'signup_with'}
                  onCredential={(token) => google.run(token)} />
              ) : (
                <p className="small muted" style={{ textAlign: 'center' }}>Enter your shop name to sign up with Google.</p>
              )}
              <ErrorAlert message={google.error} />
            </>
          ) : null}
          <p className="row small muted"><Icon name="shield" size={14} color="var(--primary)" /> 2-step verification is required on every shop account</p>
        </form>
      </div>
    </div>
  );
}

/** "Check your email": the link is sent by Firebase (or shown on screen in development).
 * This tab waits, so the link can be opened on a phone too. */
function VerifyEmailStep({ step, onNext, onBack }: {
  step: LoginStep;
  onNext: (next: LoginStep) => void;
  onBack: () => void;
}) {
  const [link, setLink] = useState(step.email_link);
  const [resent, setResent] = useState(false);
  const resend = useAction(async () => {
    const next = await api.resendEmail(step.token);
    if (next.step !== 'verify_email') return onNext(next);
    setLink(next.email_link);
    setResent(true);
  });
  useEffect(() => {
    const timer = setInterval(async () => {
      try {
        const next = await api.setupStatus(step.token);
        if (next.step !== 'verify_email') onNext(next);
      } catch {
        // keep waiting; the link may still be opened
      }
    }, 3000);
    return () => clearInterval(timer);
  }, [step.token, onNext]);

  const email = link?.email ?? 'your email';
  return (
    <div className="auth-page">
      <div className="card stack" style={{ maxWidth: 460, width: '100%', padding: 28 }}>
        <span className="stat-icon" style={{ background: 'var(--primary-soft)', color: 'var(--primary)' }}>
          <Icon name="mail" size={22} />
        </span>
        <h1>Check your email</h1>
        {link?.delivery === 'development' ? (
          <>
            <p className="muted">Email sending isn't set up yet (Firebase), so here is the link we would have emailed to <strong>{email}</strong>.</p>
            <p className="row small"><span className="badge amber">TEST MODE</span> Opening it confirms the address.</p>
            {link.dev_link ? (
              <a className="btn primary" href={link.dev_link} target="_blank" rel="noreferrer">Open the verification link</a>
            ) : null}
          </>
        ) : (
          <p className="muted">
            {resent ? 'We sent a new link to ' : 'We sent a link to '}<strong>{email}</strong>. Open it on any device
            to confirm the address (check spam if it's not there in a minute). This page continues on its own.
          </p>
        )}
        <ErrorAlert message={resend.error} />
        <p className="row small muted" style={{ gap: 8 }}><span className="spinner" aria-hidden="true" /> Waiting for you to open the link…</p>
        <div className="row between small">
          <a href="#back" onClick={(e) => { e.preventDefault(); onBack(); }}>Use a different account</a>
          <Button size="small" busy={resend.busy} onClick={() => resend.run()}>Send a new link</Button>
        </div>
      </div>
    </div>
  );
}

function CodeForm({ title, subtitle, submitLabel, onSubmit, error, busy, children }: {
  title: string;
  subtitle: string;
  submitLabel: string;
  onSubmit: (code: string) => void;
  error: string | null;
  busy: boolean;
  children?: React.ReactNode;
}) {
  const [code, setCode] = useState('');
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
      submitLabel="Verify" onSubmit={(c) => verify.run(c)}
      error={verify.error} busy={verify.busy}>
      <a href="#back" className="small" onClick={(e) => { e.preventDefault(); onBack(); }}>Use a different account</a>
    </CodeForm>
  );
}

function MfaSetup({ token, onDone }: { token: string; isNew: boolean; onDone: () => void }) {
  const [enroll, setEnroll] = useState<{ secret: string; otpauth_uri: string } | null>(null);
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
      submitLabel="Turn on & continue" onSubmit={(c) => activate.run(c)}
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

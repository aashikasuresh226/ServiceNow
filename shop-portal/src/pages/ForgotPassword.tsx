/** Forgot password: emails a reset link (the reply doesn't say whether the account exists). */
import { useState } from 'react';
import type { FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import { Icon } from '../components/Icon';
import { Logo } from '../components/Logo';
import { PasswordInput } from '../components/PasswordInput';
import { Button, ErrorAlert } from '../components/ui';
import { api } from '../lib/api';
import { useAction } from '../lib/hooks';
import { PasswordChecklist } from './Auth';

export function ForgotPasswordPage() {
  const [params] = useSearchParams();
  const [email, setEmail] = useState(params.get('email') ?? '');
  const [sent, setSent] = useState<{ devLink: string | null } | null>(null);
  const send = useAction(async () => {
    const r = await api.forgotPassword(email.trim());
    setSent({ devLink: r.dev_link });
  });

  const onSubmit = (e: FormEvent) => { e.preventDefault(); void send.run(); };

  return (
    <div className="auth-page">
      <div className="card stack" style={{ maxWidth: 440, width: '100%', padding: 28 }}>
        <Logo size={40} />
        {sent ? (
          <>
            <h1 style={{ margin: 0 }}>Check your email</h1>
            <p className="muted" style={{ margin: 0 }}>
              If there's a shop account for <b>{email.trim()}</b>, we've sent a link to reset the password.
              It works once and expires in 30 minutes. Not in your inbox? Check <b>Spam</b> or <b>Junk</b>.
            </p>
            {sent.devLink ? (
              <p className="small" style={{ margin: 0 }}>
                <span className="badge amber">TEST MODE</span> Email isn't set up, so here's the link:{' '}
                <a href={sent.devLink}>open reset link</a>
              </p>
            ) : null}
            <Link to="/login" className="small">← Back to sign in</Link>
          </>
        ) : (
          <form className="stack" onSubmit={onSubmit}>
            <h1 style={{ margin: 0 }}>Forgot your password?</h1>
            <p className="muted" style={{ margin: 0 }}>Enter your business email and we'll send you a link to choose a new one.</p>
            <div className="field">
              <label htmlFor="email">Business email</label>
              <input id="email" className="input" type="email" autoComplete="email" required value={email}
                onChange={(e) => setEmail(e.target.value)} />
            </div>
            <ErrorAlert message={send.error} />
            <Button type="submit" variant="primary" busy={send.busy} icon="mail">Email me a reset link</Button>
            <Link to="/login" className="small">← Back to sign in</Link>
          </form>
        )}
      </div>
    </div>
  );
}

/** Opened from the reset email: choose a new password. */
export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const token = params.get('t') ?? '';
  const [password, setPassword] = useState('');
  const [done, setDone] = useState(false);
  const reset = useAction(async () => {
    if (!token) throw new Error('This link is incomplete. Open it again from your email.');
    await api.resetPassword(token, password);
    setDone(true);
  });
  const onSubmit = (e: FormEvent) => { e.preventDefault(); void reset.run(); };

  return (
    <div className="auth-page">
      <div className="card stack" style={{ maxWidth: 440, width: '100%', padding: 28 }}>
        <Logo size={40} />
        {done ? (
          <>
            <span className="stat-icon" style={{ background: 'var(--success-soft)', color: 'var(--success)' }}>
              <Icon name="check" size={22} />
            </span>
            <h1 style={{ margin: 0 }}>Password changed</h1>
            <p className="muted" style={{ margin: 0 }}>
              You've been signed out on other devices. Sign in with your new password; you'll still enter
              the code from your authenticator app.
            </p>
            <Link to="/login" className="btn primary" style={{ textAlign: 'center' }}>Sign in</Link>
          </>
        ) : (
          <form className="stack" onSubmit={onSubmit}>
            <h1 style={{ margin: 0 }}>Choose a new password</h1>
            <div className="field">
              <label htmlFor="new-password">New password</label>
              <PasswordInput id="new-password" autoComplete="new-password" required minLength={8} value={password}
                onChange={(e) => setPassword(e.target.value)} />
              <PasswordChecklist password={password} />
            </div>
            <ErrorAlert message={reset.error} />
            <Button type="submit" variant="primary" busy={reset.busy}>Save new password</Button>
            <Link to="/forgot-password" className="small">Link expired? Send a new one</Link>
          </form>
        )}
      </div>
    </div>
  );
}

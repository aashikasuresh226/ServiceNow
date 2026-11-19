/** Opened from the emailed link: proves the address, then sends the person back. */
import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import { Icon } from '../components/Icon';
import { ErrorAlert } from '../components/ui';
import { api } from '../lib/api';

export function VerifyEmailPage() {
  const [params] = useSearchParams();
  const token = params.get('t') ?? '';
  const [state, setState] = useState<'working' | 'done' | 'error'>('working');
  const [error, setError] = useState<string | null>(null);
  const ran = useRef(false);

  useEffect(() => {
    if (ran.current) return;
    ran.current = true;
    (async () => {
      try {
        if (!token) throw new Error('This link is incomplete. Open it again from your email.');
        await api.verifyShopEmail(token);
        setState('done');
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Could not confirm your email.');
        setState('error');
      }
    })();
  }, [token]);

  return (
    <div className="auth-page">
      <div className="card stack" style={{ maxWidth: 440, width: '100%', padding: 28, textAlign: 'center', alignItems: 'center' }}>
        {state === 'working' ? <p className="row muted"><span className="spinner" aria-hidden="true" /> Confirming your email…</p> : null}
        {state === 'done' ? (
          <>
            <span className="stat-icon" style={{ background: 'var(--success-soft)', color: 'var(--success)' }}>
              <Icon name="check" size={22} />
            </span>
            <h1>Email confirmed</h1>
            <p className="muted">Go back to the tab where you signed up; it continues on its own.
              On a different device? <Link to="/login">Sign in here</Link>.</p>
          </>
        ) : null}
        {state === 'error' ? (
          <>
            <ErrorAlert message={error} />
            <Link to="/login">Back to sign in</Link>
          </>
        ) : null}
      </div>
    </div>
  );
}

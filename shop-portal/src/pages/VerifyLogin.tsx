/** Opened from the 2-step sign-in email: continue here, or show a code for the other device. */
import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';

import { Logo } from '../components/Logo';
import { Button, ErrorAlert } from '../components/ui';
import { api, setTokens } from '../lib/api';
import { useAction } from '../lib/hooks';

export function VerifyLoginPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const token = params.get('t') ?? '';
  const [code, setCode] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const ran = useRef(false);

  useEffect(() => {
    if (ran.current) return;
    ran.current = true;
    (async () => {
      try {
        if (!token) throw new Error('This link is incomplete. Open it again from your email.');
        setCode((await api.loginEmailOpen(token)).code);
      } catch (e) {
        setError(e instanceof Error ? e.message : 'This link is not valid.');
      }
    })();
  }, [token]);

  const here = useAction(async () => {
    setTokens(await api.loginEmailFinish(token));
    navigate('/', { replace: true });
  });

  return (
    <div className="auth-page">
      <div className="card stack" style={{ maxWidth: 440, width: '100%', padding: 28, textAlign: 'center', alignItems: 'center' }}>
        <div style={{ display: 'flex', justifyContent: 'center', width: '100%' }}><Logo size={40} /></div>
        {error ? (
          <>
            <ErrorAlert message={error} />
            <p className="muted small">Links work once and expire after 15 minutes. Sign in again to get a new one.</p>
            <Link to="/login">Back to sign in</Link>
          </>
        ) : !code ? (
          <p className="row muted"><span className="spinner" aria-hidden="true" /> Checking your link…</p>
        ) : (
          <>
            <h1 style={{ margin: 0 }}>Sign in to HVAC Connect</h1>
            <p className="muted" style={{ margin: 0 }}>Signing in on another computer? Type this code there:</p>
            <div className="login-code" aria-label={`Your code is ${code.split('').join(' ')}`}>{code.slice(0, 3)} {code.slice(3)}</div>
            <p className="small muted" style={{ margin: 0 }}>Didn't try to sign in? Don't share this code, and change your password.</p>
            <div style={{ width: '100%', borderTop: '1px solid var(--line)', margin: '6px 0' }} />
            <ErrorAlert message={here.error} />
            <Button variant="primary" busy={here.busy} onClick={() => here.run()} style={{ width: '100%' }}>
              Continue on this device instead
            </Button>
          </>
        )}
      </div>
    </div>
  );
}

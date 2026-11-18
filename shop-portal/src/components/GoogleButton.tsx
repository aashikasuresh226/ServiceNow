/**
 * "Continue with Google" via Google Identity Services. Google hands the browser a
 * signed ID token; our backend verifies it. Each attempt carries a fresh single-use
 * nonce from the backend so a captured token can't be replayed.
 */
import { useEffect, useRef, useState } from 'react';

type GoogleId = {
  initialize: (config: Record<string, unknown>) => void;
  renderButton: (el: HTMLElement, options: Record<string, unknown>) => void;
};
declare global {
  interface Window {
    google?: { accounts: { id: GoogleId } };
  }
}

let scriptPromise: Promise<void> | null = null;
function loadScript(): Promise<void> {
  scriptPromise ??= new Promise<void>((resolve, reject) => {
    if (window.google?.accounts?.id) return resolve();
    const script = document.createElement('script');
    script.src = 'https://accounts.google.com/gsi/client';
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => {
      scriptPromise = null;
      reject(new Error('load failed'));
    };
    document.head.appendChild(script);
  });
  return scriptPromise;
}

export function GoogleButton({ clientId, getNonce, onCredential, text = 'continue_with' }: {
  clientId: string;
  getNonce: () => Promise<string>;
  onCredential: (idToken: string) => Promise<unknown> | void;
  text?: 'continue_with' | 'signin_with' | 'signup_with';
}) {
  const slot = useRef<HTMLDivElement | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [failed, setFailed] = useState(false);
  const handler = useRef(onCredential);
  handler.current = onCredential;

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [nonce] = await Promise.all([getNonce(), loadScript()]);
        const id = window.google?.accounts.id;
        if (cancelled || !id || !slot.current) return;
        id.initialize({
          client_id: clientId,
          nonce,
          ux_mode: 'popup',
          auto_select: false,
          itp_support: true,
          callback: async (response: { credential?: string }) => {
            if (!response.credential) return;
            try {
              await handler.current(response.credential);
            } finally {
              setAttempt((n) => n + 1); // fresh nonce for the next try
            }
          },
        });
        slot.current.innerHTML = '';
        id.renderButton(slot.current, {
          type: 'standard', theme: 'outline', size: 'large', text, shape: 'rectangular',
          logo_alignment: 'center', width: Math.min(400, slot.current.clientWidth || 320),
        });
        setFailed(false);
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();
    return () => { cancelled = true; };
  }, [clientId, getNonce, text, attempt]);

  return (
    <div>
      <div ref={slot} style={{ minHeight: 44, display: 'flex', justifyContent: 'center' }} />
      {failed ? <p className="small muted">Google sign-in couldn't load. Check your connection.</p> : null}
    </div>
  );
}

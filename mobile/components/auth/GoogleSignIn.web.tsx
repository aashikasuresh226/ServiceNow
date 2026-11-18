/**
 * "Continue with Google" in the browser, using Google Identity Services.
 *
 * Google returns an ID token (a signed JWT) to the callback; the backend
 * verifies it. A fresh single-use nonce from the backend is bound to every
 * attempt so a token can't be replayed.
 */
import { useEffect, useRef, useState } from 'react';
import { View } from 'react-native';

import { ErrorText } from '../ui';

type GoogleCredentialResponse = { credential?: string };
type GoogleId = {
  initialize: (config: Record<string, unknown>) => void;
  renderButton: (el: HTMLElement, options: Record<string, unknown>) => void;
  cancel: () => void;
};
declare global {
  interface Window {
    google?: { accounts: { id: GoogleId } };
  }
}

const SCRIPT_URL = 'https://accounts.google.com/gsi/client';
let scriptPromise: Promise<void> | null = null;

function loadScript(): Promise<void> {
  scriptPromise ??= new Promise<void>((resolve, reject) => {
    if (window.google?.accounts?.id) return resolve();
    const script = document.createElement('script');
    script.src = SCRIPT_URL;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => {
      scriptPromise = null;
      reject(new Error("Couldn't load Google sign-in"));
    };
    document.head.appendChild(script);
  });
  return scriptPromise;
}

export type GoogleSignInProps = {
  clientId: string;
  /** Fetches a single-use nonce from our backend. */
  getNonce: () => Promise<string>;
  /** Called with Google's ID token; send it to the backend. */
  onCredential: (idToken: string) => Promise<void> | void;
  text?: 'continue_with' | 'signin_with' | 'signup_with';
};

export function GoogleSignIn({ clientId, getNonce, onCredential, text = 'continue_with' }: GoogleSignInProps) {
  const slot = useRef<HTMLDivElement | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [error, setError] = useState<string | null>(null);
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
          callback: async (response: GoogleCredentialResponse) => {
            if (!response.credential) return;
            try {
              await handler.current(response.credential);
            } finally {
              setAttempt((n) => n + 1); // new nonce for any next attempt
            }
          },
        });
        slot.current.innerHTML = '';
        id.renderButton(slot.current, {
          type: 'standard',
          theme: 'outline',
          size: 'large',
          shape: 'pill',
          text,
          logo_alignment: 'center',
          width: Math.min(360, slot.current.clientWidth || 320),
        });
        setError(null);
      } catch {
        if (!cancelled) setError("Google sign-in couldn't load. Check your connection.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [clientId, getNonce, text, attempt]);

  return (
    <View style={{ gap: 6, alignItems: 'center' }}>
      <div ref={slot} style={{ width: '100%', minHeight: 44, display: 'flex', justifyContent: 'center' }} />
      {error ? <ErrorText message={error} /> : null}
    </View>
  );
}

export function googleSignInAvailable(): boolean {
  return true;
}



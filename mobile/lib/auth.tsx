/** Session state: tokens persisted securely, current homeowner profile, sign in/out. */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';

import { api, bindTokenStore } from './api';
import { getItem, removeItem, setItem } from './storage';
import type { Homeowner, Tokens } from './types';

const STORAGE_KEY = 'hvac.session';

type AuthState = {
  ready: boolean;
  tokens: Tokens | null;
  me: Homeowner | null;
  signIn: (tokens: Tokens) => Promise<Homeowner>;
  signOut: () => Promise<void>;
  refreshMe: () => Promise<Homeowner | null>;
  setMe: (me: Homeowner) => void;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [tokens, setTokens] = useState<Tokens | null>(null);
  const [me, setMe] = useState<Homeowner | null>(null);
  const tokensRef = useRef<Tokens | null>(null);

  const persist = useCallback((next: Tokens | null) => {
    tokensRef.current = next;
    setTokens(next);
    if (next) void setItem(STORAGE_KEY, JSON.stringify(next));
    else {
      void removeItem(STORAGE_KEY);
      setMe(null);
    }
  }, []);

  useEffect(() => {
    bindTokenStore({ get: () => tokensRef.current, set: persist });
  }, [persist]);

  const refreshMe = useCallback(async () => {
    if (!tokensRef.current) return null;
    try {
      const profile = await api.me();
      setMe(profile);
      return profile;
    } catch {
      return null;
    }
  }, []);

  // Restore a saved session on launch.
  useEffect(() => {
    (async () => {
      const saved = await getItem(STORAGE_KEY);
      if (saved) {
        try {
          tokensRef.current = JSON.parse(saved) as Tokens;
          setTokens(tokensRef.current);
          if (!(await refreshMe())) persist(null);
        } catch {
          persist(null);
        }
      }
      setReady(true);
    })();
  }, [persist, refreshMe]);

  const signIn = useCallback(
    async (next: Tokens) => {
      persist(next);
      const profile = await api.me();
      setMe(profile);
      return profile;
    },
    [persist],
  );

  const signOut = useCallback(async () => {
    const current = tokensRef.current;
    persist(null);
    if (current) await api.logout(current.refresh_token).catch(() => undefined);
  }, [persist]);

  const value = useMemo(
    () => ({ ready, tokens, me, signIn, signOut, refreshMe, setMe }),
    [ready, tokens, me, signIn, signOut, refreshMe],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}

/** Where a signed-in homeowner should go next, based on what's missing. */
export function nextOnboardingRoute(me: Homeowner): '/profile' | '/payment' | '/home' {
  if (!me.name || !me.address) return '/profile';
  if (!me.payment_method_label) return '/payment';
  return '/home';
}

/** Session state: tokens persisted securely, the signed-in homeowner or technician, sign in/out. */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';

import { api, bindTokenStore, techApi } from './api';
import { getItem, removeItem, setItem } from './storage';
import type { Homeowner, Options, TechMe, Tokens } from './types';

export type Role = 'homeowner' | 'technician';
type Session = Tokens & { role?: Role };

const STORAGE_KEY = 'hvac.session';

type AuthState = {
  ready: boolean;
  tokens: Tokens | null;
  role: Role;
  me: Homeowner | null;
  tech: TechMe | null;
  signIn: (tokens: Tokens) => Promise<Homeowner>;
  signInTech: (tokens: Tokens) => Promise<TechMe>;
  signOut: () => Promise<void>;
  refreshMe: () => Promise<Homeowner | null>;
  setMe: (me: Homeowner) => void;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [tokens, setTokens] = useState<Tokens | null>(null);
  const [me, setMe] = useState<Homeowner | null>(null);
  const [tech, setTech] = useState<TechMe | null>(null);
  const [role, setRole] = useState<Role>('homeowner');
  const tokensRef = useRef<Tokens | null>(null);
  const roleRef = useRef<Role>('homeowner');

  const persist = useCallback((next: Tokens | null, nextRole?: Role) => {
    if (nextRole) {
      roleRef.current = nextRole;
      setRole(nextRole);
    }
    tokensRef.current = next;
    setTokens(next);
    if (next) void setItem(STORAGE_KEY, JSON.stringify({ ...next, role: roleRef.current }));
    else {
      void removeItem(STORAGE_KEY);
      setMe(null);
      setTech(null);
    }
  }, []);

  useEffect(() => {
    bindTokenStore({ get: () => tokensRef.current, set: (t) => persist(t) });
  }, [persist]);

  const refreshMe = useCallback(async () => {
    if (!tokensRef.current) return null;
    try {
      if (roleRef.current === 'technician') {
        setTech(await techApi.me());
        return null;
      }
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
          const session = JSON.parse(saved) as Session;
          roleRef.current = session.role ?? 'homeowner';
          setRole(roleRef.current);
          tokensRef.current = session;
          setTokens(session);
          if (roleRef.current === 'technician') {
            try {
              setTech(await techApi.me());
            } catch {
              persist(null);
            }
          } else if (!(await refreshMe())) persist(null);
        } catch {
          persist(null);
        }
      }
      setReady(true);
    })();
  }, [persist, refreshMe]);

  const signIn = useCallback(
    async (next: Tokens) => {
      persist(next, 'homeowner');
      const profile = await api.me();
      setMe(profile);
      return profile;
    },
    [persist],
  );

  const signInTech = useCallback(
    async (next: Tokens) => {
      persist(next, 'technician');
      const profile = await techApi.me();
      setTech(profile);
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
    () => ({ ready, tokens, role, me, tech, signIn, signInTech, signOut, refreshMe, setMe }),
    [ready, tokens, role, me, tech, signIn, signInTech, signOut, refreshMe],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}

/** Where a signed-in homeowner should go next, based on what's missing. */
export function nextOnboardingRoute(
  me: Homeowner,
  options: Options | null,
): '/profile' | '/payment' | '/home' {
  if (!me.name || !me.address || !me.phone) return '/profile';
  if (options?.features.payments && !me.payment_method_label) return '/payment';
  return '/home';
}

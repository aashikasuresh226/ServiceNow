/** Session state. Customers and technicians have separate sign-ins, each saved on its own,
 * so the same phone or browser can be signed in as both: customer screens use the customer
 * sign-in, technician screens (/tech) the technician one. */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';

import { api, bindTokenStore, techApi } from './api';
import type { Role } from './api';
import { acceptPendingInvite } from './invite';
import { getItem, removeItem, setItem } from './storage';
import type { Homeowner, Options, TechMe, Tokens } from './types';

export type { Role };

const STORAGE_KEYS: Record<Role, string> = {
  homeowner: 'hvac.session.customer',
  technician: 'hvac.session.technician',
};
const OLD_STORAGE_KEY = 'hvac.session'; // before the two were separate: { ...tokens, role }

type AuthState = {
  ready: boolean;
  /** Customer sign-in. */
  tokens: Tokens | null;
  me: Homeowner | null;
  signIn: (tokens: Tokens) => Promise<Homeowner>;
  signOut: () => Promise<void>;
  refreshMe: () => Promise<Homeowner | null>;
  setMe: (me: Homeowner) => void;
  /** Technician sign-in. */
  techTokens: Tokens | null;
  tech: TechMe | null;
  signInTech: (tokens: Tokens) => Promise<TechMe>;
  signOutTech: () => Promise<void>;
  refreshTech: () => Promise<TechMe | null>;
};

const AuthContext = createContext<AuthState | null>(null);

/** One role's saved tokens: kept in a ref for the API client and in state for screens. */
function useSession(role: Role, onCleared: () => void) {
  const [tokens, setTokens] = useState<Tokens | null>(null);
  const ref = useRef<Tokens | null>(null);
  const clearedRef = useRef(onCleared);
  clearedRef.current = onCleared;
  const persist = useCallback((next: Tokens | null) => {
    ref.current = next;
    setTokens(next);
    if (next) void setItem(STORAGE_KEYS[role], JSON.stringify(next));
    else {
      void removeItem(STORAGE_KEYS[role]);
      clearedRef.current();
    }
  }, [role]);
  useEffect(() => {
    bindTokenStore(role, { get: () => ref.current, set: persist });
  }, [role, persist]);
  return { tokens, ref, persist };
}

async function loadSaved(role: Role): Promise<Tokens | null> {
  try {
    const saved = await getItem(STORAGE_KEYS[role]);
    if (saved) return JSON.parse(saved) as Tokens;
    // Move a session saved by an older version of the app to its role's place.
    const old = await getItem(OLD_STORAGE_KEY);
    if (!old) return null;
    const session = JSON.parse(old) as Tokens & { role?: Role };
    if ((session.role ?? 'homeowner') !== role) return null;
    await removeItem(OLD_STORAGE_KEY);
    const { role: _role, ...tokens } = session;
    await setItem(STORAGE_KEYS[role], JSON.stringify(tokens));
    return tokens;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [me, setMe] = useState<Homeowner | null>(null);
  const [tech, setTech] = useState<TechMe | null>(null);
  const customer = useSession('homeowner', () => setMe(null));
  const technician = useSession('technician', () => setTech(null));

  const refreshMe = useCallback(async () => {
    if (!customer.ref.current) return null;
    try {
      const profile = await api.me();
      setMe(profile);
      return profile;
    } catch {
      return null;
    }
  }, [customer.ref]);

  const refreshTech = useCallback(async () => {
    if (!technician.ref.current) return null;
    try {
      const profile = await techApi.me();
      setTech(profile);
      return profile;
    } catch {
      return null;
    }
  }, [technician.ref]);

  // Restore both saved sign-ins on launch.
  useEffect(() => {
    (async () => {
      const [savedCustomer, savedTech] = await Promise.all([
        loadSaved('homeowner'), loadSaved('technician'),
      ]);
      if (savedCustomer) {
        customer.ref.current = savedCustomer;
        customer.persist(savedCustomer);
        if (!(await refreshMe())) customer.persist(null);
      }
      if (savedTech) {
        technician.ref.current = savedTech;
        technician.persist(savedTech);
        if (!(await refreshTech())) technician.persist(null);
      }
      setReady(true);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const signIn = useCallback(async (next: Tokens) => {
    customer.persist(next);
    // Signed up from a company's invite link: become that company's customer.
    await acceptPendingInvite();
    const profile = await api.me();
    setMe(profile);
    return profile;
  }, [customer.persist]);

  const signInTech = useCallback(async (next: Tokens) => {
    technician.persist(next);
    const profile = await techApi.me();
    setTech(profile);
    return profile;
  }, [technician.persist]);

  const signOut = useCallback(async () => {
    const current = customer.ref.current;
    customer.persist(null);
    if (current) await api.logout(current.refresh_token).catch(() => undefined);
  }, [customer.persist, customer.ref]);

  const signOutTech = useCallback(async () => {
    const current = technician.ref.current;
    technician.persist(null);
    if (current) await api.logout(current.refresh_token).catch(() => undefined);
  }, [technician.persist, technician.ref]);

  const value = useMemo(
    () => ({
      ready, tokens: customer.tokens, me, signIn, signOut, refreshMe, setMe,
      techTokens: technician.tokens, tech, signInTech, signOutTech, refreshTech,
    }),
    [ready, customer.tokens, me, signIn, signOut, refreshMe, technician.tokens, tech, signInTech,
      signOutTech, refreshTech],
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

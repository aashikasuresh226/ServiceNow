import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';

import { api, ApiError } from './api';
import type { Options, ShopMe } from './types';

export function useAction<A extends unknown[], R>(fn: (...args: A) => Promise<R>) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ref = useRef(fn);
  ref.current = fn;
  const run = useCallback(async (...args: A): Promise<R | undefined> => {
    setBusy(true);
    setError(null);
    try {
      return await ref.current(...args);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Something went wrong. Please try again.');
      return undefined;
    } finally {
      setBusy(false);
    }
  }, []);
  return { run, busy, error, setError };
}

/** Load data, then refresh it every `intervalMs` (0 = load once). */
export function useLiveData<T>(load: () => Promise<T>, intervalMs = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const ref = useRef(load);
  ref.current = load;
  const reload = useCallback(async () => {
    try {
      setData(await ref.current());
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not load data');
    }
  }, []);
  useEffect(() => {
    void reload();
    if (!intervalMs) return;
    const t = setInterval(() => {
      if (document.visibilityState === 'visible') void reload();
    }, intervalMs);
    return () => clearInterval(t);
  }, [reload, intervalMs]);
  return { data, error, reload, setData };
}

export function useCountdown(until: string | null): number | null {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!until) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [until]);
  return until ? Math.max(0, Math.round((new Date(until).getTime() - now) / 1000)) : null;
}

type PortalState = {
  me: ShopMe;
  setMe: (me: ShopMe) => void;
  options: Options | null;
};

export const PortalContext = createContext<PortalState | null>(null);

export function usePortal(): PortalState {
  const ctx = useContext(PortalContext);
  if (!ctx) throw new Error('usePortal must be used inside the signed-in layout');
  return ctx;
}

export function useOptions(): Options | null {
  const [options, setOptions] = useState<Options | null>(null);
  useEffect(() => {
    api.options().then(setOptions).catch(() => undefined);
  }, []);
  return options;
}

export function label(options: Options | null, group: 'symptoms' | 'equipment_types' |
  'certifications' | 'soft_skills', value: string): string {
  return options?.[group].find((o) => o.value === value)?.label ?? value;
}

export const money = (cents: number | null | undefined) =>
  cents == null ? '—' : `$${(cents / 100).toLocaleString('en-US', { minimumFractionDigits: cents % 100 ? 2 : 0 })}`;

export const clock = (iso: string) =>
  new Date(iso).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });

export const countdownLabel = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;

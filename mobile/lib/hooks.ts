import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';

import { api, ApiError, UserError } from './api';
import type { Options } from './types';

/** Run an async action with loading + error state; errors are shown, not thrown. */
export function useAction<A extends unknown[], R>(fn: (...args: A) => Promise<R>) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const run = useCallback(
    async (...args: A): Promise<R | undefined> => {
      setBusy(true);
      setError(null);
      try {
        return await fnRef.current(...args);
      } catch (e) {
        setError(
          e instanceof ApiError || e instanceof UserError
            ? e.message
            : 'Something went wrong. Please try again.',
        );
        return undefined;
      } finally {
        setBusy(false);
      }
    },
    [],
  );
  return { run, busy, error, setError };
}

/** Re-run `fn` every `intervalMs` while `enabled`. Stops on unmount. */
export function usePolling(fn: () => Promise<unknown>, intervalMs: number, enabled: boolean) {
  const fnRef = useRef(fn);
  fnRef.current = fn;
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        await fnRef.current();
      } finally {
        if (!cancelled) timer = setTimeout(tick, intervalMs);
      }
    };
    timer = setTimeout(tick, intervalMs);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [intervalMs, enabled]);
}

/** Seconds remaining until an ISO timestamp, updated every second. */
export function useCountdown(until: string | null): number | null {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!until) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [until]);
  if (!until) return null;
  return Math.max(0, Math.round((new Date(until).getTime() - now) / 1000));
}

export const OptionsContext = createContext<Options | null>(null);

export function useOptions(): Options | null {
  return useContext(OptionsContext);
}

export function useLoadOptions(): Options | null {
  const [options, setOptions] = useState<Options | null>(null);
  useEffect(() => {
    let alive = true;
    const load = async (attempt: number) => {
      try {
        const loaded = await api.options();
        if (alive) setOptions(loaded);
      } catch {
        if (alive && attempt < 5) setTimeout(() => load(attempt + 1), 1500 * attempt);
      }
    };
    void load(1);
    return () => {
      alive = false;
    };
  }, []);
  return options;
}

export function labelFor(options: Options | null, group: keyof Options, value: string): string {
  const list = options?.[group];
  if (Array.isArray(list)) return list.find((o) => o.value === value)?.label ?? value;
  return value;
}

/** Typed client for the shop endpoints. Refreshes an expired session once, then gives up. */
import type {
  Dashboard,
  Job,
  LoginStep,
  Options,
  ShopMe,
  TechDay,
  Technician,
  Tokens,
} from './types';

export const API_URL = (import.meta.env.VITE_API_URL ?? 'http://localhost:8000/v1').replace(/\/$/, '');
const STORAGE_KEY = 'hvac.shop.session';

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

let tokens: Tokens | null = readTokens();
let onSignedOut: () => void = () => undefined;
let refreshing: Promise<boolean> | null = null;

function readTokens(): Tokens | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Tokens) : null;
  } catch {
    return null;
  }
}

export function setTokens(next: Tokens | null): void {
  tokens = next;
  try {
    if (next) window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    else window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // storage blocked: session lasts for this tab only
  }
  if (!next) onSignedOut();
}

export function hasSession(): boolean {
  return tokens !== null;
}

export function onSignOut(handler: () => void): void {
  onSignedOut = handler;
}

async function refresh(): Promise<boolean> {
  if (!tokens) return false;
  const current = tokens;
  refreshing ??= (async () => {
    try {
      const r = await fetch(`${API_URL}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: current.refresh_token }),
      });
      if (!r.ok) {
        setTokens(null);
        return false;
      }
      setTokens((await r.json()) as Tokens);
      return true;
    } catch {
      return false;
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
}

async function request<T>(method: string, path: string, body?: unknown,
  opts: { token?: string; retry?: boolean } = {}): Promise<T> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const bearer = opts.token ?? tokens?.access_token;
  if (bearer) headers.Authorization = `Bearer ${bearer}`;
  let r: Response;
  try {
    r = await fetch(`${API_URL}${path}`, {
      method, headers, body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, 'network', "Can't reach the server. Is the API running?");
  }
  if (r.status === 401 && !opts.token && opts.retry !== false && tokens && (await refresh())) {
    return request<T>(method, path, body, { retry: false });
  }
  if (!r.ok) {
    let message = 'Something went wrong. Please try again.';
    let code = 'error';
    try {
      const err = (await r.json())?.error;
      if (err?.message) {
        message = err.message;
        code = err.code ?? code;
      }
    } catch {
      // keep the generic message
    }
    throw new ApiError(r.status, code, message);
  }
  return (r.status === 204 ? undefined : await r.json()) as T;
}

export const api = {
  options: () => request<Options>('GET', '/meta/options'),

  signup: (data: { email: string; password: string; shop_name: string; name?: string }) =>
    request<LoginStep>('POST', '/auth/shop/signup', data),
  login: (email: string, password: string) =>
    request<LoginStep>('POST', '/auth/shop/login', { email, password }),
  loginMfa: (token: string, code: string) =>
    request<Tokens>('POST', '/auth/shop/login/mfa', { token, code }),
  enrollMfa: (setupToken: string) =>
    request<{ secret: string; otpauth_uri: string; dev_code: string | null }>(
      'POST', '/auth/shop/mfa/enroll', undefined, { token: setupToken }),
  activateMfa: (setupToken: string, code: string) =>
    request<Tokens>('POST', '/auth/shop/mfa/activate', { code }, { token: setupToken }),
  logout: () => tokens
    ? request<void>('POST', '/auth/logout', { refresh_token: tokens.refresh_token }).catch(() => undefined)
    : Promise.resolve(),

  me: () => request<ShopMe>('GET', '/shop/me'),
  updateShop: (data: Partial<{ name: string; phone: string; address: string; timezone: string }>) =>
    request<ShopMe>('PATCH', '/shop/me', data),
  setLive: (is_live: boolean) => request<ShopMe>('PUT', '/shop/live', { is_live }),
  payoutLink: () => request<{ url: string }>('POST', '/shop/payouts/onboarding-link'),
  refreshPayouts: () => request<ShopMe>('POST', '/shop/payouts/refresh'),
  payoutSchedule: (schedule: string) => request<ShopMe>('PUT', '/shop/payouts/schedule', { schedule }),

  connectScheduling: (provider: string, credentials: Record<string, string>, write_back_jobs: boolean) =>
    request<{ count: number }>('PUT', '/shop/scheduling', { provider, credentials, write_back_jobs }),
  disconnectScheduling: () => request<void>('DELETE', '/shop/scheduling'),
  syncNow: () => request<{ count: number }>('POST', '/shop/scheduling/sync'),

  technicians: () => request<Technician[]>('GET', '/shop/technicians'),
  createTechnician: (data: Partial<Technician>) => request<Technician>('POST', '/shop/technicians', data),
  updateTechnician: (id: string, data: Partial<Technician>) =>
    request<Technician>('PATCH', `/shop/technicians/${id}`, data),
  markBusy: (id: string, minutes: number) =>
    request<Technician>('POST', `/shop/technicians/${id}/busy`, { minutes }),
  clearBusy: (id: string) => request<Technician>('DELETE', `/shop/technicians/${id}/busy`),
  importTechnicians: () => request<{ count: number }>('POST', '/shop/technicians/import'),

  availability: () => request<TechDay[]>('GET', '/shop/availability'),
  dashboard: () => request<Dashboard>('GET', '/shop/dashboard'),

  jobs: (status?: string[]) =>
    request<Job[]>('GET', `/shop/jobs${status?.length ? `?${status.map((s) => `status=${s}`).join('&')}` : ''}`),
  accept: (id: string, technician_id?: string) =>
    request<Job>('POST', `/shop/jobs/${id}/accept`, technician_id ? { technician_id } : {}),
  decline: (id: string) => request<void>('POST', `/shop/jobs/${id}/decline`),
  enRoute: (id: string) => request<Job>('POST', `/shop/jobs/${id}/en-route`),
  onSite: (id: string) => request<Job>('POST', `/shop/jobs/${id}/on-site`),
  quote: (id: string, final_price_cents: number, notes: string) =>
    request<Job>('POST', `/shop/jobs/${id}/quote`, { final_price_cents, notes }),
  complete: (id: string) => request<Job>('POST', `/shop/jobs/${id}/complete`),
};

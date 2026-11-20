/** Typed client for the shop endpoints. Refreshes an expired session once, then gives up. */
import type {
  CalendarLink,
  Customer,
  CustomerList,
  OutsideJob,
  HcpActivity,
  ShopComplaint,
  AdminComplaint,
  AdminReview,
  Dashboard,
  Readiness,
  EmailLink,
  Job,
  LoginStep,
  Message,
  Shop,
  TechOption,
  TechPermissions,
  TimeOff,
  Options,
  ShopMe,
  TechDay,
  Technician,
  Tokens,
} from './types';

/** The API's address. On a host like Render this can be just the API's host name
 * (e.g. hvac-api.onrender.com): https:// and /v1 are added. */
function apiUrl(value: string | undefined): string {
  const raw = (value ?? '').trim().replace(/\/$/, '');
  if (!raw) return 'http://localhost:8000/v1';
  if (raw.includes('://')) return raw;
  return `https://${raw}/v1`;
}

export const API_URL = apiUrl(import.meta.env.VITE_API_URL);
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

  complaints: () => request<ShopComplaint[]>('GET', '/shop/complaints'),
  respondComplaint: (id: string, response: string, resolved: boolean) =>
    request<ShopComplaint>('POST', `/shop/complaints/${id}/response`, { response, resolved }),

  hcpActivity: () => request<HcpActivity>('GET', '/shop/housecall-pro/activity'),
  hcpSyncNow: () => request<HcpActivity>('POST', '/shop/housecall-pro/sync-now'),

  outsideJobs: () => request<OutsideJob[]>('GET', '/shop/outside-jobs'),
  customers: (q?: string, status?: string) => {
    const params = new URLSearchParams();
    if (q) params.set('q', q);
    if (status) params.set('status', status);
    const qs = params.toString();
    return request<CustomerList>('GET', `/shop/customers${qs ? `?${qs}` : ''}`);
  },
  markInvited: (id: string) => request<Customer>('POST', `/shop/customers/${id}/invited`),
  importCustomers: () => request<{ count: number }>('POST', '/shop/customers/import'),

  signup: (data: { email: string; password: string; shop_name: string; name?: string }) =>
    request<LoginStep>('POST', '/auth/shop/signup', data),
  login: (email: string, password: string) =>
    request<LoginStep>('POST', '/auth/shop/login', { email, password }),
  googleNonce: () => request<{ nonce: string }>('POST', '/auth/google/nonce'),
  google: (id_token: string, shop_name?: string) =>
    request<LoginStep>('POST', '/auth/shop/google', shop_name ? { id_token, shop_name } : { id_token }),
  setupStatus: (setupToken: string) =>
    request<LoginStep>('GET', '/auth/shop/setup-status', undefined, { token: setupToken }),
  resendEmail: (setupToken: string) =>
    request<LoginStep>('POST', '/auth/shop/resend-email', undefined, { token: setupToken }),
  emailProofInfo: (token: string) =>
    request<{ email: string; purpose: string }>('GET', `/auth/email-proof/${encodeURIComponent(token)}`),
  verifyShopEmail: (token: string) =>
    request<void>('POST', '/auth/shop/verify-email', { token }),
  loginMfa: (token: string, code: string) =>
    request<Tokens>('POST', '/auth/shop/login/mfa', { token, code }),
  enrollMfa: (setupToken: string) =>
    request<{ secret: string; otpauth_uri: string }>(
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
  setDispatch: (data: Partial<Pick<Shop, 'dispatch_mode' | 'instant_book' | 'instant_book_daily_limit'>>) =>
    request<ShopMe>('PATCH', '/shop/dispatch', data),

  technicians: () => request<Technician[]>('GET', '/shop/technicians'),
  createTechnician: (data: Partial<Technician>) => request<Technician>('POST', '/shop/technicians', data),
  updateTechnician: (id: string, data: Partial<Technician>) =>
    request<Technician>('PATCH', `/shop/technicians/${id}`, data),
  markBusy: (id: string, minutes: number) =>
    request<Technician>('POST', `/shop/technicians/${id}/busy`, { minutes }),
  clearBusy: (id: string) => request<Technician>('DELETE', `/shop/technicians/${id}/busy`),
  inviteTechnician: (id: string, email: string, permissions: TechPermissions) =>
    request<{ technician: Technician; email_link: EmailLink }>(
      'POST', `/shop/technicians/${id}/invite`, { email, ...permissions }),
  removeAppAccess: (id: string) => request<Technician>('DELETE', `/shop/technicians/${id}/app-access`),
  timeOff: (id: string) => request<TimeOff[]>('GET', `/shop/technicians/${id}/time-off`),
  addTimeOff: (id: string, starts_at: string, ends_at: string, label: string) =>
    request<TimeOff>('POST', `/shop/technicians/${id}/time-off`, { starts_at, ends_at, label }),
  removeTimeOff: (id: string, blockId: string) =>
    request<void>('DELETE', `/shop/technicians/${id}/time-off/${blockId}`),
  importTechnicians: () => request<{ count: number }>('POST', '/shop/technicians/import'),

  calendarLink: (id: string, rotate = false) =>
    request<CalendarLink>('GET', `/shop/technicians/${id}/calendar${rotate ? '?rotate=true' : ''}`),

  availability: (day?: string) =>
    request<TechDay[]>('GET', `/shop/availability${day ? `?day=${day}` : ''}`),
  readiness: () => request<Readiness>('GET', '/shop/readiness'),
  dashboard: () => request<Dashboard>('GET', '/shop/dashboard'),

  jobs: (status?: string[]) =>
    request<Job[]>('GET', `/shop/jobs${status?.length ? `?${status.map((s) => `status=${s}`).join('&')}` : ''}`),
  technicianOptions: (id: string) => request<TechOption[]>('GET', `/shop/jobs/${id}/technician-options`),
  accept: (id: string, technician_id?: string) =>
    request<Job>('POST', `/shop/jobs/${id}/accept`, technician_id ? { technician_id } : {}),
  decline: (id: string) => request<void>('POST', `/shop/jobs/${id}/decline`),
  enRoute: (id: string) => request<Job>('POST', `/shop/jobs/${id}/en-route`),
  onSite: (id: string) => request<Job>('POST', `/shop/jobs/${id}/on-site`),
  quote: (id: string, final_price_cents: number, notes: string, actual_issue?: string) =>
    request<Job>('POST', `/shop/jobs/${id}/quote`, { final_price_cents, notes, actual_issue: actual_issue || undefined }),
  complete: (id: string) => request<Job>('POST', `/shop/jobs/${id}/complete`),
  messages: (id: string) => request<Message[]>('GET', `/shop/jobs/${id}/messages`),
  sendMessage: (id: string, body: string) =>
    request<Message>('POST', `/shop/jobs/${id}/messages`, { body }),
};

/** Platform admin (you): signed in with HVAC_ADMIN_TOKEN, kept for this browser tab only. */
const ADMIN_KEY = 'hvac.admin.key';

export function getAdminKey(): string | null {
  try {
    return window.sessionStorage.getItem(ADMIN_KEY);
  } catch {
    return null;
  }
}

export function setAdminKey(key: string | null): void {
  try {
    if (key) window.sessionStorage.setItem(ADMIN_KEY, key);
    else window.sessionStorage.removeItem(ADMIN_KEY);
  } catch {
    // storage blocked: the page asks again
  }
}

async function adminRequest<T>(method: string, path: string, body?: unknown, key = getAdminKey()): Promise<T> {
  const r = await fetch(`${API_URL}/admin${path}`, {
    method,
    headers: { 'Content-Type': 'application/json', 'X-Admin-Key': key ?? '' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = r.status === 204 ? null : await r.json().catch(() => null);
  if (!r.ok) {
    const error = (data as { error?: { code?: string; message?: string } } | null)?.error;
    throw new ApiError(r.status, error?.code ?? 'error', error?.message ?? `Request failed (${r.status})`);
  }
  return data as T;
}

export const adminApi = {
  check: (key: string) => adminRequest<{ ok: boolean }>('GET', '/check', undefined, key),
  complaints: (status?: string) =>
    adminRequest<AdminComplaint[]>('GET', `/complaints${status ? `?status=${status}` : ''}`),
  updateComplaint: (id: string, note: string | null, status?: 'open' | 'resolved') =>
    adminRequest<AdminComplaint>('PATCH', `/complaints/${id}`, { note, status }),
  reviews: () => adminRequest<AdminReview[]>('GET', '/reviews'),
  trainingData: async (): Promise<Blob> => {
    const r = await fetch(`${API_URL}/admin/training-data`, { headers: { 'X-Admin-Key': getAdminKey() ?? '' } });
    if (!r.ok) throw new ApiError(r.status, 'error', `Download failed (${r.status})`);
    return r.blob();
  },
};

/**
 * Typed API client. Handles auth headers, refreshes expired sessions once,
 * and turns error responses into ApiError with the backend's message.
 */
import { Platform } from 'react-native';

import { API_URL } from './config';
import type { AuthenticatorSetupData } from '@/components/AuthenticatorSetup';
import type {
  CardSetup,
  Homeowner,
  InviteInfo,
  Message,
  Options,
  OutsideJob,
  OutsideJobDetail,
  OutsideStep,
  UnreadChat,
  HomeVisit,
  Complaint,
  ComplaintState,
  Providers,
  PublicProvider,
  ShareInfo,
  ServiceRequest,
  TechBoard,
  TechJob,
  TechMe,
  Tokens,
} from './types';

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

/** An error whose message is safe and helpful to show the user (e.g. "Card declined"). */
export class UserError extends Error {}

type TokenStore = {
  get: () => Tokens | null;
  set: (tokens: Tokens | null) => void;
};

let tokenStore: TokenStore = { get: () => null, set: () => undefined };
let refreshing: Promise<boolean> | null = null;

/** Called once by the auth provider so the client can read and rotate tokens. */
export function bindTokenStore(store: TokenStore): void {
  tokenStore = store;
}

async function parseError(response: Response): Promise<ApiError> {
  try {
    const body = await response.json();
    const err = body?.error;
    if (err?.message) return new ApiError(response.status, err.code ?? 'error', err.message);
  } catch {
    // fall through
  }
  return new ApiError(response.status, 'error', 'Something went wrong. Please try again.');
}

async function refreshSession(): Promise<boolean> {
  const current = tokenStore.get();
  if (!current) return false;
  refreshing ??= (async () => {
    try {
      const response = await fetch(`${API_URL}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: current.refresh_token }),
      });
      if (!response.ok) {
        tokenStore.set(null);
        return false;
      }
      tokenStore.set((await response.json()) as Tokens);
      return true;
    } catch {
      return false;
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  { auth = true, retry = true }: { auth?: boolean; retry?: boolean } = {},
): Promise<T> {
  const headers: Record<string, string> = {};
  const isForm = typeof FormData !== 'undefined' && body instanceof FormData;
  if (body !== undefined && !isForm) headers['Content-Type'] = 'application/json';
  const tokens = auth ? tokenStore.get() : null;
  if (tokens) headers.Authorization = `Bearer ${tokens.access_token}`;

  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, 'network', `Can't reach the server (${API_URL}). Check your connection.`);
  }

  if (response.status === 401 && auth && retry && tokens) {
    if (await refreshSession()) return request<T>(method, path, body, { auth, retry: false });
  }
  if (!response.ok) throw await parseError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  options: () => request<Options>('GET', '/meta/options', undefined, { auth: false }),

  // Auth
  homeownerStart: (phone: string) =>
    request<{ account: 'existing' | 'new'; setup: AuthenticatorSetupData | null }>(
      'POST', '/auth/homeowner/start', { phone }, { auth: false }),
  homeownerSignup: (phone: string, setup_token: string, code: string) =>
    request<Tokens & { needs_profile: boolean; backup_codes: string[] }>(
      'POST', '/auth/homeowner/signup', { phone, setup_token, code }, { auth: false }),
  homeownerLogin: (phone: string, code: string) =>
    request<Tokens & { needs_profile: boolean }>(
      'POST', '/auth/homeowner/login', { phone, code }, { auth: false }),
  googleNonce: () =>
    request<{ nonce: string }>('POST', '/auth/google/nonce', undefined, { auth: false }),
  googleSignIn: (idToken: string) =>
    request<Tokens & { needs_profile: boolean }>(
      'POST',
      '/auth/homeowner/google',
      { id_token: idToken },
      { auth: false },
    ),
  logout: (refreshToken: string) =>
    request<void>('POST', '/auth/logout', { refresh_token: refreshToken }, { auth: false }),

  // Profile + card
  me: () => request<Homeowner>('GET', '/me'),
  visits: () => request<HomeVisit[]>('GET', '/me/visits'),
  notifications: () =>
    request<{ unread_messages: UnreadChat[]; total_unread: number }>('GET', '/me/notifications'),
  complaint: (id: string) => request<ComplaintState>('GET', `/requests/${id}/complaint`),
  fileComplaint: (id: string, category: string, details: string) =>
    request<Complaint>('POST', `/requests/${id}/complaint`, { category, details }),
  suggestions: () => request<{ name: string | null; address: string | null; companies: string[] }>('GET', '/me/suggestions'),
  inviteInfo: (code: string) =>
    request<{ shop_name: string; shop_phone: string | null }>('GET', `/invites/${encodeURIComponent(code)}`, undefined, { auth: false }),
  acceptInvite: (code: string) =>
    request<{ shop_name: string; shop_phone: string | null }>('POST', '/me/invite', { code }),
  updateMe: (data: Partial<Pick<Homeowner, 'name' | 'address' | 'sms_opt_in'>>) =>
    request<Homeowner>('PATCH', '/me', data),
  setPhone: (phone: string) => request<Homeowner>('POST', '/me/phone', { phone }),
  startCardSetup: () => request<CardSetup>('POST', '/me/payment-methods/setup'),
  finishCardSetup: (setupIntentId: string) =>
    request<Homeowner>('POST', '/me/payment-methods/finish', { setup_intent_id: setupIntentId }),

  // Requests
  listRequests: () => request<ServiceRequest[]>('GET', '/requests'),
  getRequest: (id: string) => request<ServiceRequest>('GET', `/requests/${id}`),
  createRequest: (data: { symptoms: string[]; description: string; urgency: string }) =>
    request<ServiceRequest>('POST', '/requests', data),
  uploadPhoto: async (id: string, uri: string, mimeType = 'image/jpeg') => {
    const form = new FormData();
    if (Platform.OS === 'web') {
      const blob = await (await fetch(uri)).blob();
      form.append('file', blob, 'unit.jpg');
    } else {
      // React Native's FormData accepts a file descriptor object.
      form.append('file', { uri, name: 'unit.jpg', type: mimeType } as unknown as Blob);
    }
    return request<ServiceRequest>('POST', `/requests/${id}/photos`, form);
  },
  analyze: (id: string) => request<ServiceRequest>('POST', `/requests/${id}/analyze`),
  updateUnit: (id: string, data: Partial<UnitUpdate>) =>
    request<ServiceRequest>('PATCH', `/requests/${id}/unit`, data),
  /** Book the soonest technician, or the company / technician the homeowner picked. */
  match: (id: string, choice?: { shop_id?: string; technician_id?: string }) =>
    request<ServiceRequest>('POST', `/requests/${id}/match`, choice ?? {}),
  providers: (id: string) => request<Providers>('GET', `/requests/${id}/providers`),
  share: (id: string) => request<ShareInfo>('GET', `/requests/${id}/share`),
  publicTechnician: (id: string) =>
    request<PublicProvider>('GET', `/providers/technicians/${id}`, undefined, { auth: false }),
  publicShop: (id: string) =>
    request<PublicProvider>('GET', `/providers/shops/${id}`, undefined, { auth: false }),
  confirm: (id: string) => request<ServiceRequest>('POST', `/requests/${id}/confirm`),
  approveQuote: (id: string) => request<ServiceRequest>('POST', `/requests/${id}/approve-quote`),
  cancel: (id: string) => request<ServiceRequest>('POST', `/requests/${id}/cancel`),
  messages: (id: string) => request<Message[]>('GET', `/requests/${id}/messages`),
  sendMessage: (id: string, body: string) =>
    request<Message>('POST', `/requests/${id}/messages`, { body }),
  rate: (id: string, ratings: { technician_rating?: number; shop_rating?: number; review?: string }) =>
    request<ServiceRequest>('POST', `/requests/${id}/rating`, ratings),
};

/** Technician app. */
export const techApi = {
  inviteInfo: (token: string) =>
    request<InviteInfo>('GET', `/auth/technician/invite/${encodeURIComponent(token)}`, undefined, { auth: false }),
  verifyInviteEmail: (token: string) =>
    request<{ claim: string }>('POST', '/auth/technician/invite/verify-email',
      { token }, { auth: false }),
  inviteAuthenticator: (token: string, claim: string) =>
    request<AuthenticatorSetupData>('POST', '/auth/technician/invite/authenticator', { token, claim }, { auth: false }),
  acceptInvite: (data: {
    token: string; claim: string; phone?: string; setup_token?: string; code?: string; google_id_token?: string;
  }) => request<Tokens & { backup_codes: string[] }>('POST', '/auth/technician/invite/accept', data, { auth: false }),
  login: (login: string, code: string) =>
    request<Tokens>('POST', '/auth/technician/login', { login, code }, { auth: false }),
  google: (id_token: string) =>
    request<Tokens>('POST', '/auth/technician/google', { id_token }, { auth: false }),

  me: () => request<TechMe>('GET', '/tech/me'),
  board: () => request<TechBoard>('GET', '/tech/jobs'),
  outsideJob: (id: string) => request<OutsideJobDetail>('GET', `/tech/outside-jobs/${id}`),
  outsideStep: (id: string, step: OutsideStep, summary?: string, actual_issue?: string) =>
    request<OutsideJobDetail>('POST', `/tech/outside-jobs/${id}/step`, { step, summary, actual_issue }),
  outsideLineItem: (id: string, name: string, quantity: number, unit_price_cents: number) =>
    request<OutsideJobDetail>('POST', `/tech/outside-jobs/${id}/line-items`, { name, quantity, unit_price_cents }),
  outsideNote: (id: string, body: string) =>
    request<OutsideJobDetail>('POST', `/tech/outside-jobs/${id}/notes`, { body }),
  outsideRetry: (id: string) => request<OutsideJobDetail>('POST', `/tech/outside-jobs/${id}/retry`),
  outsidePhoto: async (id: string, uri: string, mimeType = 'image/jpeg') => {
    const form = new FormData();
    if (Platform.OS === 'web') {
      const blob = await (await fetch(uri)).blob();
      form.append('file', blob, 'job.jpg');
    } else {
      form.append('file', { uri, name: 'job.jpg', type: mimeType } as unknown as Blob);
    }
    return request<OutsideJobDetail>('POST', `/tech/outside-jobs/${id}/photos`, form);
  },
  job: (id: string) => request<TechJob>('GET', `/tech/jobs/${id}`),
  accept: (id: string) => request<TechJob>('POST', `/tech/jobs/${id}/accept`),
  decline: (id: string, reason?: string) => request<void>('POST', `/tech/jobs/${id}/decline`, { reason }),
  cantMakeIt: (id: string, reason?: string) =>
    request<TechJob>('POST', `/tech/jobs/${id}/cant-make-it`, { reason }),
  startDriving: (id: string) => request<TechJob>('POST', `/tech/jobs/${id}/start-driving`),
  location: (id: string, lat: number, lng: number, accuracy_m?: number | null) =>
    request<void>('PUT', `/tech/jobs/${id}/location`, { lat, lng, accuracy_m: accuracy_m ?? null }),
  arrived: (id: string) => request<TechJob>('POST', `/tech/jobs/${id}/arrived`),
  quote: (id: string, final_price_cents: number, notes: string, actual_issue?: string) =>
    request<TechJob>('POST', `/tech/jobs/${id}/quote`, { final_price_cents, notes, actual_issue }),
  complete: (id: string) => request<TechJob>('POST', `/tech/jobs/${id}/complete`),
  messages: (id: string) => request<Message[]>('GET', `/tech/jobs/${id}/messages`),
  sendMessage: (id: string, body: string) =>
    request<Message>('POST', `/tech/jobs/${id}/messages`, { body }),
};

export type UnitUpdate = {
  brand: string;
  model_number: string;
  equipment_type: string;
  approx_age_years: number;
};

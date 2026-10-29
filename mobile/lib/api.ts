/**
 * Typed API client. Handles auth headers, refreshes expired sessions once,
 * and turns error responses into ApiError with the backend's message.
 */
import { Platform } from 'react-native';

import { API_URL } from './config';
import type {
  CardSetup,
  Homeowner,
  Options,
  ServiceRequest,
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
    throw new ApiError(0, 'network', "Can't reach the server. Check your connection.");
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
  startOtp: (phone: string) =>
    request<{ phone: string; resend_after_seconds: number; dev_code: string | null }>(
      'POST',
      '/auth/homeowner/otp/start',
      { phone },
      { auth: false },
    ),
  verifyOtp: (phone: string, code: string) =>
    request<Tokens & { needs_profile: boolean }>(
      'POST',
      '/auth/homeowner/otp/verify',
      { phone, code },
      { auth: false },
    ),
  logout: (refreshToken: string) =>
    request<void>('POST', '/auth/logout', { refresh_token: refreshToken }, { auth: false }),

  // Profile + card
  me: () => request<Homeowner>('GET', '/me'),
  updateMe: (data: Partial<Pick<Homeowner, 'name' | 'address' | 'sms_opt_in'>>) =>
    request<Homeowner>('PATCH', '/me', data),
  startCardSetup: () => request<CardSetup>('POST', '/me/payment-methods/setup'),
  demoCard: (setupIntentId: string, cardNumber: string) =>
    request<void>('POST', '/me/payment-methods/demo-card', {
      setup_intent_id: setupIntentId,
      card_number: cardNumber,
    }),
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
  setPreferences: (id: string, softSkills: string[], requireAll: boolean) =>
    request<ServiceRequest>('PUT', `/requests/${id}/preferences`, {
      soft_skills: softSkills,
      require_all: requireAll,
    }),
  match: (id: string) => request<ServiceRequest>('POST', `/requests/${id}/match`),
  confirm: (id: string) => request<ServiceRequest>('POST', `/requests/${id}/confirm`),
  widen: (id: string) => request<ServiceRequest>('POST', `/requests/${id}/widen`),
  approveQuote: (id: string) => request<ServiceRequest>('POST', `/requests/${id}/approve-quote`),
  cancel: (id: string) => request<ServiceRequest>('POST', `/requests/${id}/cancel`),
  rate: (id: string, rating: number) =>
    request<ServiceRequest>('POST', `/requests/${id}/rating`, { rating }),
};

export type UnitUpdate = {
  brand: string;
  model_number: string;
  equipment_type: string;
  approx_age_years: number;
};

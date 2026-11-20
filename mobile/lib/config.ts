/** App-wide constants. Rebrand here. */
export const APP_NAME = 'HVAC Connect';

/** The API's address. On a host like Render this can be just the API's host name
 * (e.g. hvac-api.onrender.com): https:// and /v1 are added. */
export function apiUrl(value: string | undefined): string {
  const raw = (value ?? '').trim().replace(/\/$/, '');
  if (!raw) return 'http://localhost:8000/v1';
  if (raw.includes('://')) return raw;
  return `https://${raw}/v1`;
}

export const API_URL = apiUrl(process.env.EXPO_PUBLIC_API_URL);

/** How often live screens refresh while waiting on the other side. */
export const POLL_INTERVAL_MS = 3000;

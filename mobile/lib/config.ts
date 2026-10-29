/** App-wide constants. Rebrand here. */
export const APP_NAME = 'HVAC Connect';

export const API_URL = (process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000/v1').replace(
  /\/$/,
  '',
);

/** How often live screens refresh while waiting on the other side. */
export const POLL_INTERVAL_MS = 3000;

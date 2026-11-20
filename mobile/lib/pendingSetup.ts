/** The authenticator setup in progress, handed from the welcome screen to the setup screen
 * (kept in memory, not in the URL, because it holds the secret). */
import type { AuthenticatorSetupData } from '@/components/AuthenticatorSetup';

let pending: { phone: string; setup: AuthenticatorSetupData } | null = null;

export function setPendingSetup(value: { phone: string; setup: AuthenticatorSetupData } | null): void {
  pending = value;
}

export function getPendingSetup(): { phone: string; setup: AuthenticatorSetupData } | null {
  return pending;
}

/**
 * A company or technician the homeowner chose from a shared link, remembered until
 * their next request (they may have to sign in first).
 */
import { getItem, removeItem, setItem } from './storage';

export type PendingChoice = { kind: 'shop' | 'technician'; id: string; name: string };

const KEY = 'hvac.pendingChoice';

export async function rememberChoice(choice: PendingChoice): Promise<void> {
  await setItem(KEY, JSON.stringify(choice));
}

export async function takeChoice(): Promise<PendingChoice | null> {
  const raw = await getItem(KEY);
  if (!raw) return null;
  await removeItem(KEY);
  try {
    const parsed = JSON.parse(raw) as PendingChoice;
    return parsed.kind && parsed.id ? parsed : null;
  } catch {
    return null;
  }
}

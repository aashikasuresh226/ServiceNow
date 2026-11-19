/** A company's invite link (/join/<code>) opened before signing in: remembered until the
 * homeowner has an account, then sent to the API so they become that company's customer. */
import { api } from '@/lib/api';
import { getItem, removeItem, setItem } from '@/lib/storage';

const KEY = 'pending_invite';

export type PendingInvite = { code: string; shopName: string };

export async function savePendingInvite(invite: PendingInvite): Promise<void> {
  await setItem(KEY, JSON.stringify(invite));
}

export async function getPendingInvite(): Promise<PendingInvite | null> {
  try {
    const raw = await getItem(KEY);
    return raw ? (JSON.parse(raw) as PendingInvite) : null;
  } catch {
    return null;
  }
}

/** Call once signed in as a homeowner. Never throws: an invite is a nice-to-have. */
export async function acceptPendingInvite(): Promise<void> {
  const invite = await getPendingInvite();
  if (!invite) return;
  try {
    await api.acceptInvite(invite.code);
    await removeItem(KEY);
  } catch (e) {
    const status = (e as { status?: number }).status;
    if (status === 404) await removeItem(KEY); // link no longer valid
  }
}

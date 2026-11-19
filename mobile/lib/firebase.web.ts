/** Finishes Firebase's email-link sign-in on the page opened from the invite email.
 * We only use the result to prove the technician owns the invited address. */
import { UserError } from './api';
import type { FirebaseConfig } from './types';

export async function finishEmailLink(config: FirebaseConfig, email: string): Promise<string> {
  const { initializeApp, getApps } = await import('firebase/app');
  const { getAuth, isSignInWithEmailLink, signInWithEmailLink, signOut } = await import('firebase/auth');
  const auth = getAuth(getApps()[0] ?? initializeApp(config));
  const href = window.location.href;
  if (!isSignInWithEmailLink(auth, href)) {
    throw new UserError('Open the invite link from your email to continue.');
  }
  try {
    const result = await signInWithEmailLink(auth, email, href);
    const token = await result.user.getIdToken();
    await signOut(auth);
    return token;
  } catch (e) {
    const code = (e as { code?: string })?.code ?? '';
    if (code.includes('invalid-action-code') || code.includes('expired')) {
      throw new UserError('This invite link expired or was already used. Ask your company to resend it.');
    }
    throw new UserError('Could not confirm your email. Please open the link again.');
  }
}

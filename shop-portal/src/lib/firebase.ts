/**
 * Firebase Authentication (free plan), used only to email links that prove an
 * address is real: shop sign-up and technician invites. Loaded on demand.
 */
import type { EmailLink, FirebaseConfig } from './types';

const EMAIL_KEY = 'hvac.emailForSignIn';

async function auth(config: FirebaseConfig) {
  const { initializeApp, getApps } = await import('firebase/app');
  const { getAuth } = await import('firebase/auth');
  const app = getApps()[0] ?? initializeApp(config);
  return getAuth(app);
}

/** Ask Firebase to email `link.continue_url` to `link.email`. */
export async function sendEmailLink(config: FirebaseConfig, link: EmailLink): Promise<void> {
  const { sendSignInLinkToEmail } = await import('firebase/auth');
  await sendSignInLinkToEmail(await auth(config), link.email, {
    url: link.continue_url,
    handleCodeInApp: true,
  });
  try {
    window.localStorage.setItem(EMAIL_KEY, link.email);
  } catch {
    // not needed: the page asks the server which address the link was for
  }
}

/** On the page opened from the email: finish Firebase's sign-in, return its ID token. */
export async function finishEmailLink(config: FirebaseConfig, email: string): Promise<string> {
  const { isSignInWithEmailLink, signInWithEmailLink, signOut } = await import('firebase/auth');
  const firebaseAuth = await auth(config);
  const href = window.location.href;
  if (!isSignInWithEmailLink(firebaseAuth, href)) {
    throw new Error('Open the newest link from your email to continue.');
  }
  const result = await signInWithEmailLink(firebaseAuth, email, href);
  const token = await result.user.getIdToken();
  await signOut(firebaseAuth); // we only needed the proof; the app has its own sessions
  return token;
}

export function firebaseErrorMessage(error: unknown): string {
  const code = (error as { code?: string })?.code ?? '';
  if (code.includes('invalid-action-code') || code.includes('expired')) {
    return 'This link expired or was already used. Ask for a new one.';
  }
  if (code.includes('unauthorized-continue-uri') || code.includes('unauthorized-domain')) {
    return 'Add this website to Firebase > Authentication > Settings > Authorized domains.';
  }
  if (code.includes('operation-not-allowed')) {
    return 'Turn on "Email link (passwordless sign-in)" in Firebase > Authentication > Sign-in method.';
  }
  if (code.includes('quota')) return 'Firebase\'s free daily email limit was reached. Try again tomorrow.';
  return error instanceof Error ? error.message : 'Could not send the email. Please try again.';
}

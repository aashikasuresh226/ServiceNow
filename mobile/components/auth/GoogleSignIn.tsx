/**
 * iOS/Android: "Continue with Google" will use the native Google Sign-In SDK
 * (separate iOS and Android OAuth client IDs) when the mobile apps are built.
 * Until then, phone sign-in is offered on mobile. Web version: GoogleSignIn.web.tsx.
 */
export type GoogleSignInProps = {
  clientId: string;
  getNonce: () => Promise<string>;
  onCredential: (idToken: string) => Promise<void> | void;
  text?: 'continue_with' | 'signin_with' | 'signup_with';
};

export function GoogleSignIn(_props: GoogleSignInProps) {
  return null;
}

export function googleSignInAvailable(): boolean {
  return false;
}

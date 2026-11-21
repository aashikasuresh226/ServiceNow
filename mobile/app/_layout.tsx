import { Stack, router, useSegments } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import Head from 'expo-router/head';
import { useEffect } from 'react';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { Loading } from '@/components/ui';
import { AuthProvider, useAuth } from '@/lib/auth';
import { APP_NAME } from '@/lib/config';
import { OptionsContext, useLoadOptions } from '@/lib/hooks';
import { UnreadProvider } from '@/lib/unread';

// 'p' = public company / technician pages opened from shared links; 'join' = a company's invite.
const PUBLIC_ROUTES = new Set(['welcome', 'verify', 'authenticator', 'email', 'email-sign-in', 'p', 'join']);
// Technician screens anyone can open: sign-in and the emailed invite.
const PUBLIC_TECH_ROUTES = new Set(['sign-in', 'join', 'email-sign-in']);

/** Customer screens need the customer sign-in, technician screens (/tech) the technician
 * one. The two are separate, so being signed in as one never affects the other. */
function AuthGate() {
  const { ready, tokens, techTokens } = useAuth();
  const segments = useSegments() as string[];
  const first = segments[0] ?? '';
  const second = segments[1] ?? '';
  const isPublic = PUBLIC_ROUTES.has(first) || (first === 'tech' && PUBLIC_TECH_ROUTES.has(second));

  useEffect(() => {
    if (!ready) return;
    if (first === 'tech') {
      if (!techTokens && !isPublic) router.replace('/tech/sign-in');
      else if (techTokens && second === 'sign-in') router.replace('/tech');
      return;
    }
    if (!tokens && !isPublic) router.replace('/welcome');
  }, [ready, tokens, techTokens, first, second, isPublic]);

  if (!ready) return <Loading />;
  return <Stack screenOptions={{ headerShown: false, animation: 'slide_from_right' }} />;
}

export default function RootLayout() {
  const options = useLoadOptions();
  return (
    <SafeAreaProvider>
      <Head>
        <title>{APP_NAME}</title>
      </Head>
      <OptionsContext.Provider value={options}>
        <AuthProvider>
          <StatusBar style="dark" />
          <UnreadProvider>
            <AuthGate />
          </UnreadProvider>
        </AuthProvider>
      </OptionsContext.Provider>
    </SafeAreaProvider>
  );
}

import { Stack, router, useSegments } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import Head from 'expo-router/head';
import { useEffect } from 'react';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { Loading } from '@/components/ui';
import { AuthProvider, useAuth } from '@/lib/auth';
import { APP_NAME } from '@/lib/config';
import { OptionsContext, useLoadOptions } from '@/lib/hooks';

// 'p' = public company / technician pages opened from shared links; 'join' = a company's invite.
const PUBLIC_ROUTES = new Set(['welcome', 'verify', 'p', 'join']);
// Technician screens anyone can open: sign-in and the emailed invite.
const PUBLIC_TECH_ROUTES = new Set(['sign-in', 'join']);

/** Sends signed-out users to the welcome screen, and each role to its own screens. */
function AuthGate() {
  const { ready, tokens, role } = useAuth();
  const segments = useSegments() as string[];
  const first = segments[0] ?? '';
  const second = segments[1] ?? '';
  const isPublic = PUBLIC_ROUTES.has(first) || (first === 'tech' && PUBLIC_TECH_ROUTES.has(second));

  useEffect(() => {
    if (!ready) return;
    if (!tokens) {
      if (!isPublic) router.replace(first === 'tech' ? '/tech/sign-in' : '/welcome');
      return;
    }
    if (isPublic || first === 'p') return;
    if (role === 'technician' && first !== 'tech') router.replace('/tech');
    if (role === 'homeowner' && first === 'tech') router.replace('/home');
  }, [ready, tokens, role, first, isPublic]);

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
          <AuthGate />
        </AuthProvider>
      </OptionsContext.Provider>
    </SafeAreaProvider>
  );
}

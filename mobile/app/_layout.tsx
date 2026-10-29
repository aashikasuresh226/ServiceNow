import { Stack, router, useSegments } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import Head from 'expo-router/head';
import { useEffect } from 'react';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { Loading } from '@/components/ui';
import { AuthProvider, useAuth } from '@/lib/auth';
import { APP_NAME } from '@/lib/config';
import { OptionsContext, useLoadOptions } from '@/lib/hooks';

const PUBLIC_ROUTES = new Set(['welcome', 'verify']);

/** Sends signed-out users to the welcome screen. */
function AuthGate() {
  const { ready, tokens } = useAuth();
  const segments = useSegments();
  const first = segments[0] ?? '';

  useEffect(() => {
    if (!ready) return;
    if (!tokens && !PUBLIC_ROUTES.has(first)) router.replace('/welcome');
  }, [ready, tokens, first]);

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

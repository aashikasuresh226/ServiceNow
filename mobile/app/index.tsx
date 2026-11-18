import { Redirect } from 'expo-router';

import { Loading } from '@/components/ui';
import { nextOnboardingRoute, useAuth } from '@/lib/auth';
import { useOptions } from '@/lib/hooks';

export default function Index() {
  const { ready, tokens, me } = useAuth();
  const options = useOptions();
  if (!ready) return <Loading />;
  if (!tokens) return <Redirect href="/welcome" />;
  if (!me || !options) return <Loading />;
  return <Redirect href={nextOnboardingRoute(me, options)} />;
}

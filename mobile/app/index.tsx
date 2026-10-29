import { Redirect } from 'expo-router';

import { Loading } from '@/components/ui';
import { nextOnboardingRoute, useAuth } from '@/lib/auth';

export default function Index() {
  const { ready, tokens, me } = useAuth();
  if (!ready || (tokens && !me)) return <Loading />;
  if (!tokens || !me) return <Redirect href="/welcome" />;
  return <Redirect href={nextOnboardingRoute(me)} />;
}

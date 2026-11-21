/** Opened from an emailed link (technicians): ?t=… signs in; ?r=1&t=… recovers a lost authenticator. */
import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useRef, useState } from 'react';

import { Icon } from '@/components/icons';
import { colors } from '@/components/theme';
import { Button, Card, ErrorText, Loading, Muted, Screen, Title } from '@/components/ui';
import { techApi } from '@/lib/api';
import { useAuth } from '@/lib/auth';

export default function TechEmailLinkLanding() {
  const { t = '', r } = useLocalSearchParams<{ t: string; r?: string }>();
  const { signInTech } = useAuth();
  const [recovered, setRecovered] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ran = useRef(false);

  useEffect(() => {
    if (ran.current) return;
    ran.current = true;
    (async () => {
      try {
        if (!t) throw new Error('This link is incomplete. Open it again from your email.');
        if (r) {
          await signInTech(await techApi.recoverFinish(t));
          setRecovered(true);
        } else {
          await signInTech(await techApi.emailFinish(t));
          router.replace('/tech');
        }
      } catch (e) {
        setError(e instanceof Error && e.message ? e.message : 'This link is not valid.');
      }
    })();
  }, [t, r, signInTech]);

  if (error) {
    return (
      <Screen footer={<Button label="Back to sign in" onPress={() => router.replace('/tech/sign-in')} />}>
        <Title>That link didn't work</Title>
        <ErrorText message={error} />
        <Muted>Links work once and expire after a short time. Ask for a new one from the sign-in screen.</Muted>
      </Screen>
    );
  }
  if (!recovered) return <Loading label="Checking your link…" />;
  return (
    <Screen footer={<Button label="Continue" onPress={() => router.replace('/tech')} />}>
      <Card tone="soft" style={{ alignItems: 'center', paddingVertical: 20 }}>
        <Icon name="check" size={34} color={colors.success} strokeWidth={3} />
      </Card>
      <Title sub="You're signed in, and the old authenticator was removed. From now on, use “Email me a sign-in link” on the sign-in screen. Any other devices were signed out.">
        Account recovered
      </Title>
    </Screen>
  );
}

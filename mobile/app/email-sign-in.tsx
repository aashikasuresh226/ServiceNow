/**
 * Opened from an emailed link (homeowners):
 *   ?t=…(&p=…)  sign in (or create the account)    ?r=1&t=…  recovery    ?c=1&t=…  confirm a recovery email
 * Signs in on the device where the link is opened.
 */
import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useRef, useState } from 'react';

import { Icon } from '@/components/icons';
import { colors } from '@/components/theme';
import { Button, Card, ErrorText, Loading, Muted, Screen, Title } from '@/components/ui';
import { api } from '@/lib/api';
import { nextOnboardingRoute, useAuth } from '@/lib/auth';
import { useOptions } from '@/lib/hooks';
import type { Homeowner } from '@/lib/types';

export default function EmailLinkLanding() {
  const { t = '', p, r, c } = useLocalSearchParams<{ t: string; p?: string; r?: string; c?: string }>();
  const options = useOptions();
  const { signIn, tokens } = useAuth();
  const [done, setDone] = useState<{ kind: 'recovered' | 'confirmed'; me?: Homeowner; email?: string | null } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const ran = useRef(false);

  useEffect(() => {
    if (!options || ran.current) return;
    ran.current = true;
    (async () => {
      try {
        if (!t) throw new Error('This link is incomplete. Open it again from your email.');
        if (c) {
          const confirmed = await api.confirmEmail(t);
          setDone({ kind: 'confirmed', email: confirmed.sent_to });
        } else if (r) {
          const me = await signIn(await api.homeownerRecoverFinish(t));
          setDone({ kind: 'recovered', me });
        } else {
          const me = await signIn(await api.homeownerEmailFinish(t, p));
          router.replace(nextOnboardingRoute(me, options));
        }
      } catch (e) {
        setError(e instanceof Error && e.message ? e.message : 'This link is not valid.');
      }
    })();
  }, [options, t, p, r, c, signIn]);

  if (error) {
    return (
      <Screen footer={<Button label="Back to sign in" onPress={() => router.replace('/welcome')} />}>
        <Title>That link didn't work</Title>
        <ErrorText message={error} />
        <Muted>Links work once and expire after a short time. Ask for a new one from the sign-in screen.</Muted>
      </Screen>
    );
  }
  if (!done) return <Loading label="Checking your link…" />;
  const next = () => router.replace(done.me ? nextOnboardingRoute(done.me, options) : tokens ? '/account' : '/welcome');
  return (
    <Screen footer={<Button label="Continue" onPress={next} />}>
      <Card tone="soft" style={{ alignItems: 'center', paddingVertical: 20 }}>
        <Icon name="check" size={34} color={colors.success} strokeWidth={3} />
      </Card>
      {done.kind === 'confirmed' ? (
        <Title sub={`${done.email ?? 'Your email'} is saved for account recovery. If you ever lose your authenticator, we can email you a recovery link.`}>
          Email confirmed
        </Title>
      ) : (
        <Title sub="You're signed in, and the old authenticator was removed. From now on, we'll email you a link each time you sign in. Any other devices were signed out.">
          Account recovered
        </Title>
      )}
    </Screen>
  );
}

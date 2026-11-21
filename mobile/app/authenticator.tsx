/** New homeowner: choose how to sign in (an emailed link, or an authenticator app), then
 * set up the authenticator and save the backup codes if they chose the app. */
import { router } from 'expo-router';
import { useEffect, useState } from 'react';

import { AuthenticatorSetup, BackupCodes } from '@/components/AuthenticatorSetup';
import { Icon } from '@/components/icons';
import { colors } from '@/components/theme';
import { Body, Button, Card, Muted, Row, Screen, StepHeader, TextLink, Title } from '@/components/ui';
import { Pressable, View } from 'react-native';
import { api } from '@/lib/api';
import { nextOnboardingRoute, useAuth } from '@/lib/auth';
import { formatPhone } from '@/lib/format';
import { useAction, useOptions } from '@/lib/hooks';
import { getPendingSetup, setPendingSetup } from '@/lib/pendingSetup';
import type { Homeowner } from '@/lib/types';

export default function AuthenticatorScreen() {
  const options = useOptions();
  const { signIn } = useAuth();
  const [pending] = useState(getPendingSetup);
  const [code, setCode] = useState('');
  const [useApp, setUseApp] = useState(false);
  const [backup, setBackup] = useState<{ codes: string[]; me: Homeowner } | null>(null);

  useEffect(() => {
    if (!pending) router.replace('/welcome'); // e.g. the page was reloaded: start again
  }, [pending]);

  const finish = useAction(async () => {
    const session = await api.homeownerSignup(pending!.phone, pending!.setup.setup_token, code);
    const me = await signIn(session);
    setPendingSetup(null);
    setBackup({ codes: session.backup_codes, me });
  });

  if (!pending) return null;
  const useEmail = () => router.replace({ pathname: '/email', params: { phone: pending.phone, mode: 'new' } });
  if (!useApp && !backup) {
    return (
      <Screen>
        <StepHeader />
        <Title sub={`New account for ${formatPhone(pending.phone)}. No passwords: choose how you'll sign in.`}>
          How do you want to sign in?
        </Title>
        <Choice icon="mail" title="Email me a link" recommended
          text="No app needed. Each time you sign in, tap the link we email you." onPress={useEmail} />
        <Choice icon="shield" title="Authenticator app"
          text="Extra secure. Google Authenticator, Microsoft Authenticator or your phone's passwords app."
          onPress={() => setUseApp(true)} />
      </Screen>
    );
  }
  if (backup) {
    return (
      <Screen footer={<Button label="I saved my backup codes" onPress={() => router.replace(nextOnboardingRoute(backup.me, options))} />}>
        <Title sub="You're signed in. Next time, just enter the code from your authenticator app.">Save your backup codes</Title>
        <BackupCodes codes={backup.codes} />
      </Screen>
    );
  }
  return (
    <Screen footer={<Button label="Create my account" busy={finish.busy} disabled={code.length !== 6} onPress={() => finish.run()} />}>
      <StepHeader />
      <Title sub={`New account for ${formatPhone(pending.phone)}. Instead of texting you codes, your phone makes them.`}>
        Set up sign-in
      </Title>
      <AuthenticatorSetup setup={pending.setup} code={code} onCode={(v) => { finish.setError(null); setCode(v); }} error={finish.error} />
      <TextLink label="No authenticator app? Sign in with email instead" onPress={useEmail} />
    </Screen>
  );
}

function Choice({ icon, title, text, recommended, onPress }: {
  icon: 'mail' | 'shield'; title: string; text: string; recommended?: boolean; onPress: () => void;
}) {
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={title} onPress={onPress}>
      {({ pressed }) => (
        <Card style={{ gap: 6, borderColor: pressed || recommended ? colors.primary : colors.line, borderWidth: recommended ? 2 : 1 }}>
          <Row style={{ gap: 12 }}>
            <View style={{ width: 44, height: 44, borderRadius: 12, backgroundColor: colors.primarySoft,
              alignItems: 'center', justifyContent: 'center' }}>
              <Icon name={icon} size={22} color={colors.primary} />
            </View>
            <View style={{ flex: 1, gap: 2 }}>
              <Body style={{ fontWeight: '700' }}>{title}{recommended ? '  ·  Easiest' : ''}</Body>
              <Muted>{text}</Muted>
            </View>
            <Icon name="chevronRight" size={18} color={colors.muted} />
          </Row>
        </Card>
      )}
    </Pressable>
  );
}

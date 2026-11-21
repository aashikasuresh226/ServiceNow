/** Sign in: the 6-digit code from the authenticator app (or a backup code). */
import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { View } from 'react-native';

import { CodeInput, codeReady } from '@/components/CodeInput';
import { Icon } from '@/components/icons';
import { colors } from '@/components/theme';
import { Button, Card, ErrorText, Muted, Screen, StepHeader, Title } from '@/components/ui';
import { api } from '@/lib/api';
import { nextOnboardingRoute, useAuth } from '@/lib/auth';
import { formatPhone } from '@/lib/format';
import { useAction, useOptions } from '@/lib/hooks';

export default function Verify() {
  const { phone = '' } = useLocalSearchParams<{ phone: string }>();
  const options = useOptions();
  const { signIn } = useAuth();
  const [code, setCode] = useState('');

  const verify = useAction(async (value: string) => {
    const session = await api.homeownerLogin(phone, value);
    const me = await signIn(session);
    router.replace(nextOnboardingRoute(me, options));
  });

  useEffect(() => {
    if (/^\d{6}$/.test(code) && !verify.busy && !verify.error) void verify.run(code);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code]);

  return (
    <Screen footer={<Button label="Sign in" busy={verify.busy} disabled={!codeReady(code)}
      onPress={() => verify.run(code)} />}>
      <StepHeader />
      <Card tone="brand" style={{ alignItems: 'center', paddingVertical: 18 }}>
        <View style={{ width: 56, height: 56, borderRadius: 16, backgroundColor: colors.surface,
          alignItems: 'center', justifyContent: 'center' }}>
          <Icon name="shield" size={30} color={colors.primary} />
        </View>
      </Card>
      <Title sub={`Open your authenticator app and find the HVAC Connect code for ${formatPhone(phone)}.`}>Enter your code</Title>
      <CodeInput value={code} onChange={(v) => { verify.setError(null); setCode(v); }} allowBackup
        onSubmit={() => { if (codeReady(code)) void verify.run(code); }} />
      <ErrorText message={verify.error} />
      <Muted>The code changes every 30 seconds. If it doesn't work, check your phone's time is set automatically.</Muted>
    </Screen>
  );
}

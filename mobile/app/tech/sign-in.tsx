/** Technician sign-in: texted code or Google. Accounts are created only by a company invite. */
import { router } from 'expo-router';
import { useCallback, useState } from 'react';
import { View } from 'react-native';

import { CodeInput } from '@/components/CodeInput';
import { GoogleSignIn, googleSignInAvailable } from '@/components/auth/GoogleSignIn';
import { Icon } from '@/components/icons';
import { colors } from '@/components/theme';
import { Button, Card, ErrorText, Field, Muted, Row, Screen, TextLink, Title } from '@/components/ui';
import { api, techApi } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { formatPhone } from '@/lib/format';
import { useAction, useOptions } from '@/lib/hooks';

export default function TechSignIn() {
  const options = useOptions();
  const { signInTech } = useAuth();
  const [phone, setPhone] = useState('');
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [devCode, setDevCode] = useState<string | null>(null);
  const [code, setCode] = useState('');

  const start = useAction(async () => {
    const started = await techApi.startOtp(phone);
    setSentTo(started.phone);
    setDevCode(started.dev_code);
    setCode(started.dev_code ?? '');
  });
  const verify = useAction(async () => {
    await signInTech(await techApi.verifyOtp(sentTo!, code));
    router.replace('/tech');
  });
  const google = useAction(async (idToken: string) => {
    await signInTech(await techApi.google(idToken));
    router.replace('/tech');
  });
  const getNonce = useCallback(async () => (await api.googleNonce()).nonce, []);
  const googleClientId = options?.features.google_client_id;

  return (
    <Screen footer={
      sentTo ? (
        <Button label="Sign in" busy={verify.busy} disabled={code.length !== 6} onPress={() => verify.run()} />
      ) : (
        <Button label="Text me a code" icon="phone" busy={start.busy} onPress={() => start.run()} />
      )
    }>
      <Card tone="soft" style={{ alignItems: 'center', paddingVertical: 20, gap: 8 }}>
        <View style={{ width: 56, height: 56, borderRadius: 16, backgroundColor: colors.surface,
          alignItems: 'center', justifyContent: 'center' }}>
          <Icon name="wrench" size={30} color={colors.primary} />
        </View>
      </Card>
      <Title sub="Your jobs, schedule and customer messages.">Technician sign-in</Title>
      {sentTo ? (
        <>
          <CodeInput value={code} onChange={setCode} devCode={devCode} phoneLabel={formatPhone(sentTo)} />
          <ErrorText message={verify.error} />
          <TextLink label="Use a different number" onPress={() => { setSentTo(null); setCode(''); }} />
        </>
      ) : (
        <>
          {googleClientId && googleSignInAvailable() ? (
            <>
              <GoogleSignIn clientId={googleClientId} getNonce={getNonce} onCredential={(t) => google.run(t)} />
              <ErrorText message={google.error} />
              <Row style={{ gap: 10 }}>
                <View style={{ flex: 1, height: 1, backgroundColor: colors.line }} />
                <Muted>or use your phone</Muted>
                <View style={{ flex: 1, height: 1, backgroundColor: colors.line }} />
              </Row>
            </>
          ) : null}
          <Field label="Mobile number" value={phone} onChangeText={setPhone} placeholder="(404) 555-0123"
            keyboardType="phone-pad" autoComplete="tel" onSubmitEditing={() => start.run()} />
          <ErrorText message={start.error} />
          <Muted>New here? Your company sends you an invite by email. Open it on this phone to set up your account.</Muted>
        </>
      )}
      <TextLink label="I'm a homeowner" color={colors.muted} onPress={() => router.replace('/welcome')} />
    </Screen>
  );
}

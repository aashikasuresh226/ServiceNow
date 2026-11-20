/** Technician sign-in: phone number or email + authenticator code, or Google.
 * Accounts are created only by a company invite. */
import { router } from 'expo-router';
import { useCallback, useState } from 'react';
import { View } from 'react-native';

import { CodeInput, codeReady } from '@/components/CodeInput';
import { GoogleSignIn, googleSignInAvailable } from '@/components/auth/GoogleSignIn';
import { Icon } from '@/components/icons';
import { colors } from '@/components/theme';
import { Button, Card, ErrorText, Field, Muted, Row, Screen, Title } from '@/components/ui';
import { api, techApi } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { useAction, useOptions } from '@/lib/hooks';

export default function TechSignIn() {
  const options = useOptions();
  const { signInTech } = useAuth();
  const [login, setLogin] = useState('');
  const [code, setCode] = useState('');

  const signIn = useAction(async () => {
    await signInTech(await techApi.login(login, code));
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
      <Button label="Sign in" busy={signIn.busy} disabled={login.trim().length < 5 || !codeReady(code)}
        onPress={() => signIn.run()} />
    }>
      <Card tone="soft" style={{ alignItems: 'center', paddingVertical: 20, gap: 8 }}>
        <View style={{ width: 56, height: 56, borderRadius: 16, backgroundColor: colors.surface,
          alignItems: 'center', justifyContent: 'center' }}>
          <Icon name="wrench" size={30} color={colors.primary} />
        </View>
      </Card>
      <Title sub="Your jobs, schedule and customer messages.">Technician sign-in</Title>
      {googleClientId && googleSignInAvailable() ? (
        <>
          <GoogleSignIn clientId={googleClientId} getNonce={getNonce} onCredential={(t) => google.run(t)} />
          <ErrorText message={google.error} />
          <Row style={{ gap: 10 }}>
            <View style={{ flex: 1, height: 1, backgroundColor: colors.line }} />
            <Muted>or</Muted>
            <View style={{ flex: 1, height: 1, backgroundColor: colors.line }} />
          </Row>
        </>
      ) : null}
      <Field label="Mobile number or email" value={login} onChangeText={setLogin}
        placeholder="(404) 555-0123" autoComplete="username" autoCapitalize="none" />
      <CodeInput value={code} onChange={setCode} allowBackup onSubmit={() => signIn.run()} />
      <ErrorText message={signIn.error} />
      <Muted>
        New here? Ask your shop to invite you. The invite comes by email from HVAC Connect: if it isn't in your inbox,
        check Spam or Junk. Open it on this phone to set up your account.
      </Muted>
    </Screen>
  );
}

import { router } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { Text, View, useWindowDimensions } from 'react-native';

import { GoogleSignIn, googleSignInAvailable } from '@/components/auth/GoogleSignIn';
import { HouseIllustration } from '@/components/illustrations';
import { Logo } from '@/components/Logo';
import { colors } from '@/components/theme';
import { Badge, Body, Button, Card, ErrorText, Field, Muted, Row, Screen } from '@/components/ui';
import { api } from '@/lib/api';
import { nextOnboardingRoute, useAuth } from '@/lib/auth';
import { APP_NAME } from '@/lib/config';
import { useAction, useOptions } from '@/lib/hooks';
import { getPendingInvite } from '@/lib/invite';
import { setPendingSetup } from '@/lib/pendingSetup';

export default function Welcome() {
  const options = useOptions();
  const { signIn } = useAuth();
  const { height } = useWindowDimensions();
  const compact = height < 820;
  const [phone, setPhone] = useState('');
  const [invitedBy, setInvitedBy] = useState<string | null>(null);
  useEffect(() => { void getPendingInvite().then((i) => setInvitedBy(i?.shopName ?? null)); }, []);

  const start = useAction(async (value: string) => {
    const result = await api.homeownerStart(value);
    if (result.account === 'existing' || !result.setup) {
      router.push({ pathname: '/verify', params: { phone: value } });
    } else {
      setPendingSetup({ phone: value, setup: result.setup });
      router.push('/authenticator');
    }
  });
  const submit = (value: string) => {
    if (value.replace(/\D/g, '').length < 10) {
      start.setError('Enter your 10-digit mobile number');
      return;
    }
    void start.run(value);
  };

  const google = useAction(async (idToken: string) => {
    const session = await api.googleSignIn(idToken);
    const me = await signIn(session);
    router.replace(nextOnboardingRoute(me, options));
  });
  const getNonce = useCallback(async () => (await api.googleNonce()).nonce, []);
  const googleClientId = options?.features.google_client_id;
  const showGoogle = Boolean(googleClientId) && googleSignInAvailable();

  return (
    <Screen
      footer={
        <>
          <Button label="Continue with phone" icon="phone" busy={start.busy} onPress={() => submit(phone)} />
          <Muted style={{ textAlign: 'center', fontSize: 11 }}>
            By continuing you agree to the Terms and Privacy Policy.
          </Muted>
        </>
      }
    >
      <Card tone="soft" style={{ alignItems: 'center', paddingVertical: compact ? 10 : 24 }}>
        <HouseIllustration width={compact ? 150 : 230} />
      </Card>
      <View style={{ alignItems: 'center', gap: 2 }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
          <Logo size={compact ? 32 : 38} />
          <Text style={{ fontSize: compact ? 26 : 30, fontWeight: '800', color: colors.primaryDark, letterSpacing: -0.5 }}>
            {APP_NAME}
          </Text>
        </View>
        <Body style={{ color: colors.muted }}>HVAC help, matched in minutes</Body>
      </View>
      {invitedBy ? (
        <Card tone="muted" style={{ alignItems: 'center' }}>
          <Badge label={`Invited by ${invitedBy}`} />
          <Muted style={{ textAlign: 'center' }}>Use the number {invitedBy} has for you to connect your account.</Muted>
        </Card>
      ) : null}

      {showGoogle && googleClientId ? (
        <>
          <GoogleSignIn clientId={googleClientId} getNonce={getNonce}
            onCredential={(token) => google.run(token)} />
          <ErrorText message={google.error} />
          <Row style={{ gap: 10 }}>
            <View style={{ flex: 1, height: 1, backgroundColor: colors.line }} />
            <Muted>or use your phone</Muted>
            <View style={{ flex: 1, height: 1, backgroundColor: colors.line }} />
          </Row>
        </>
      ) : null}

      <Field
        label="Mobile number"
        value={phone}
        onChangeText={(v) => { start.setError(null); setPhone(v); }}
        placeholder="(404) 555-0123"
        keyboardType="phone-pad"
        autoComplete="tel"
        textContentType="telephoneNumber"
        onSubmitEditing={() => submit(phone)}
        returnKeyType="go"
      />
      <ErrorText message={start.error} />
      <Muted>No password: you'll sign in with a free authenticator app on your phone (we'll help you set it up).</Muted>
    </Screen>
  );
}

import { router } from 'expo-router';
import { useState } from 'react';
import { Text, View, useWindowDimensions } from 'react-native';

import { HouseIllustration } from '@/components/illustrations';
import { colors } from '@/components/theme';
import { Badge, Body, Button, Card, ErrorText, Field, Muted, Row, Screen } from '@/components/ui';
import { api } from '@/lib/api';
import { APP_NAME } from '@/lib/config';
import { useAction, useOptions } from '@/lib/hooks';

const DEMO_PHONE = '(555) 555-0100';

export default function Welcome() {
  const options = useOptions();
  const { height } = useWindowDimensions();
  const compact = height < 820;
  const [phone, setPhone] = useState('');

  const start = useAction(async (value: string) => {
    const result = await api.startOtp(value);
    router.push({
      pathname: '/verify',
      params: { phone: result.phone, devCode: result.dev_code ?? '' },
    });
  });
  const submit = (value: string) => {
    if (value.replace(/\D/g, '').length < 7) {
      start.setError('Enter your mobile number');
      return;
    }
    void start.run(value);
  };

  return (
    <Screen
      footer={
        <>
          <Button label="Continue" icon="phone" busy={start.busy} onPress={() => submit(phone)} />
          {options?.demo_mode ? (
            <Button label="Use demo homeowner" variant="secondary" disabled={start.busy}
              onPress={() => { setPhone(DEMO_PHONE); submit(DEMO_PHONE); }} />
          ) : null}
          <Muted style={{ textAlign: 'center', fontSize: 11 }}>
            By continuing you agree to the Terms and Privacy Policy. Message and data rates may apply.
          </Muted>
        </>
      }
    >
      <Card tone="soft" style={{ alignItems: 'center', paddingVertical: compact ? 12 : 28 }}>
        <HouseIllustration width={compact ? 170 : 250} />
      </Card>
      <View style={{ alignItems: 'center', gap: 2 }}>
        <Text style={{ fontSize: compact ? 26 : 30, fontWeight: '800', color: colors.ink, letterSpacing: -0.5 }}>
          {APP_NAME}
        </Text>
        <Body style={{ color: colors.muted }}>HVAC help, matched in minutes</Body>
      </View>
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
      {options?.demo_mode ? (
        <Row>
          <Badge label="DEMO MODE" tone="amber" />
          <Muted style={{ flex: 1 }}>Codes appear on screen. Any number works.</Muted>
        </Row>
      ) : (
        <Muted>We'll text you a code to sign in. No password needed.</Muted>
      )}
    </Screen>
  );
}

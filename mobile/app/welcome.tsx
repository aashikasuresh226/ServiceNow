import { router } from 'expo-router';
import { useState } from 'react';
import { Text, View } from 'react-native';

import { HouseIllustration } from '@/components/illustrations';
import { colors } from '@/components/theme';
import { Badge, Body, Button, Card, ErrorText, Field, Muted, Screen, TextLink } from '@/components/ui';
import { api } from '@/lib/api';
import { APP_NAME } from '@/lib/config';
import { useAction, useOptions } from '@/lib/hooks';

const DEMO_PHONE = '(555) 555-0100';

export default function Welcome() {
  const options = useOptions();
  const [phone, setPhone] = useState('');
  const start = useAction(async (value: string) => {
    const result = await api.startOtp(value);
    router.push({
      pathname: '/verify',
      params: { phone: result.phone, devCode: result.dev_code ?? '' },
    });
  });

  return (
    <Screen
      footer={
        <>
          <Button label="Continue" icon="phone" busy={start.busy} disabled={phone.trim().length < 7}
            onPress={() => start.run(phone)} />
          <Muted style={{ textAlign: 'center', fontSize: 11 }}>
            By continuing you agree to the Terms and Privacy Policy. Message and data rates may apply.
          </Muted>
        </>
      }
    >
      <Card tone="soft" style={{ alignItems: 'center', paddingVertical: 28 }}>
        <HouseIllustration width={250} />
      </Card>
      <View style={{ alignItems: 'center', gap: 4 }}>
        <Text style={{ fontSize: 30, fontWeight: '800', color: colors.ink, letterSpacing: -0.5 }}>
          {APP_NAME}
        </Text>
        <Body style={{ color: colors.muted }}>HVAC help, matched in minutes</Body>
      </View>
      <Field
        label="Mobile number"
        value={phone}
        onChangeText={setPhone}
        placeholder="(404) 555-0123"
        keyboardType="phone-pad"
        autoComplete="tel"
        textContentType="telephoneNumber"
        onSubmitEditing={() => phone.trim().length >= 7 && start.run(phone)}
        returnKeyType="go"
      />
      <Muted>We'll text you a code to sign in. No password needed.</Muted>
      <ErrorText message={start.error} />
      {options?.demo_mode ? (
        <Card tone="amber" style={{ gap: 6 }}>
          <Badge label="DEMO MODE" tone="amber" />
          <Muted>Use the demo homeowner, or any number. Codes appear on screen.</Muted>
          <TextLink label={`Use demo homeowner ${DEMO_PHONE}`} color={colors.amberInk}
            onPress={() => setPhone(DEMO_PHONE)} />
        </Card>
      ) : null}
    </Screen>
  );
}

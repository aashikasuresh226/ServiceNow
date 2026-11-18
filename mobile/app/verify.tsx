import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import type { ComponentRef } from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import Svg, { Circle, Rect } from 'react-native-svg';

import { colors } from '@/components/theme';
import { Badge, Button, Card, ErrorText, Muted, Screen, StepHeader, TextLink, Title } from '@/components/ui';
import { api } from '@/lib/api';
import { nextOnboardingRoute, useAuth } from '@/lib/auth';
import { formatPhone } from '@/lib/format';
import { useAction, useCountdown, useOptions } from '@/lib/hooks';
import { decorative } from '@/components/a11y';

const LENGTH = 6;

/**
 * Enter the texted code. Two uses:
 * - signing in with a phone number (default)
 * - adding a phone number to a signed-in account (purpose=add, e.g. after Google sign-in)
 */
export default function Verify() {
  const params = useLocalSearchParams<{ phone: string; devCode?: string; purpose?: string }>();
  const phone = params.phone ?? '';
  const adding = params.purpose === 'add';
  const options = useOptions();
  const { signIn, setMe } = useAuth();
  const [code, setCode] = useState(params.devCode ?? '');
  const [devCode, setDevCode] = useState(params.devCode ?? '');
  const [resendAt, setResendAt] = useState(() => new Date(Date.now() + 30_000).toISOString());
  const secondsLeft = useCountdown(resendAt) ?? 0;
  const input = useRef<ComponentRef<typeof TextInput>>(null);

  const verify = useAction(async (value: string) => {
    if (adding) {
      const me = await api.verifyAddPhone(phone, value);
      setMe(me);
      router.replace(nextOnboardingRoute(me, options));
      return;
    }
    const session = await api.verifyOtp(phone, value);
    const me = await signIn(session);
    router.replace(nextOnboardingRoute(me, options));
  });
  const resend = useAction(async () => {
    const result = adding ? await api.startAddPhone(phone) : await api.startOtp(phone);
    setResendAt(new Date(Date.now() + result.resend_after_seconds * 1000).toISOString());
    if (result.dev_code) {
      setDevCode(result.dev_code);
      setCode(result.dev_code);
    }
  });

  useEffect(() => {
    if (code.length === LENGTH && !verify.busy && !verify.error) void verify.run(code);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code]);

  return (
    <Screen footer={<Button label="Verify" busy={verify.busy} disabled={code.length !== LENGTH}
      onPress={() => verify.run(code)} />}>
      <StepHeader />
      <View style={{ alignItems: 'center' }}>
        <Svg width={88} height={88} viewBox="0 0 88 88" {...decorative}>
          <Circle cx={44} cy={44} r={44} fill={colors.primarySoft} />
          <Rect x={30} y={18} width={28} height={52} rx={5} fill="#FFFFFF" stroke={colors.ink} strokeWidth={2} />
          <Rect x={44} y={28} width={32} height={20} rx={6} fill={colors.primary} />
          <Circle cx={52} cy={38} r={2} fill="#FFFFFF" />
          <Circle cx={60} cy={38} r={2} fill="#FFFFFF" />
          <Circle cx={68} cy={38} r={2} fill="#FFFFFF" />
        </Svg>
      </View>
      <Title sub={`Sent by text to ${formatPhone(phone)}`}>Enter your code</Title>

      <Pressable onPress={() => input.current?.focus()} accessibilityLabel="Verification code">
        <View style={styles.boxes}>
          {Array.from({ length: LENGTH }, (_, i) => (
            <View key={i} style={[styles.box, i === code.length && styles.boxActive,
              i < code.length && styles.boxFilled]}>
              <Text style={styles.digit}>{code[i] ?? ''}</Text>
            </View>
          ))}
        </View>
        <TextInput
          ref={input}
          value={code}
          onChangeText={(v) => {
            verify.setError(null);
            setCode(v.replace(/\D/g, '').slice(0, LENGTH));
          }}
          keyboardType="number-pad"
          autoComplete="one-time-code"
          textContentType="oneTimeCode"
          autoFocus
          maxLength={LENGTH}
          style={styles.hiddenInput}
          accessibilityLabel="Verification code"
        />
      </Pressable>

      <ErrorText message={verify.error ?? resend.error} />
      {secondsLeft > 0 ? (
        <Muted style={{ textAlign: 'center' }}>Resend code in 0:{String(secondsLeft).padStart(2, '0')}</Muted>
      ) : (
        <TextLink label="Resend code" onPress={() => resend.run()} />
      )}
      {devCode ? (
        <Card tone="amber" style={{ gap: 6 }}>
          <Badge label="TEST MODE" tone="amber" />
          <Muted>
            Texting isn't set up yet (no Twilio keys), so code {devCode} was filled in for you.
            Once Twilio is connected, codes arrive by text only.
          </Muted>
        </Card>
      ) : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  boxes: { flexDirection: 'row', gap: 8, justifyContent: 'center' },
  box: {
    width: 44,
    height: 54,
    borderRadius: 12,
    borderWidth: 1.5,
    borderColor: colors.lineStrong,
    backgroundColor: colors.surface,
    alignItems: 'center',
    justifyContent: 'center',
  },
  boxActive: { borderColor: colors.primary, borderWidth: 2 },
  boxFilled: { borderColor: colors.ink },
  digit: { fontSize: 22, fontWeight: '700', color: colors.ink },
  hiddenInput: { position: 'absolute', opacity: 0, height: 1, width: 1 },
});

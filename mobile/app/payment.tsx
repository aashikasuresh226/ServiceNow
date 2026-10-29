import { router, useLocalSearchParams } from 'expo-router';
import { View } from 'react-native';

import { Icon } from '@/components/icons';
import { PaymentSetup } from '@/components/payment/PaymentSetup';
import { colors } from '@/components/theme';
import { Body, Card, Muted, Screen, StepHeader, TextLink, Title } from '@/components/ui';
import { useAuth } from '@/lib/auth';

const STEPS = [
  { icon: 'lock' as const, text: 'Hold placed when you book' },
  { icon: 'wrench' as const, text: 'You approve the final price' },
  { icon: 'check' as const, text: 'Charged when the job is done' },
];

export default function Payment() {
  const { setMe } = useAuth();
  const { returnTo } = useLocalSearchParams<{ returnTo?: string }>();
  const done = () => router.replace((returnTo as '/home' | undefined) ?? '/home');

  return (
    <Screen>
      {returnTo ? <StepHeader /> : null}
      <Title sub="Pay in the app, like a ride app. No cash or checks.">Add a payment method</Title>
      <Card tone="soft" style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
        {STEPS.map((s, i) => (
          <View key={s.text} style={{ flex: 1, alignItems: 'center', gap: 6 }}>
            <View style={{ width: 36, height: 36, borderRadius: 18, alignItems: 'center',
              justifyContent: 'center', backgroundColor: i === 2 ? colors.primary : '#FFFFFF' }}>
              <Icon name={s.icon} size={18} color={i === 2 ? '#FFFFFF' : colors.primary} />
            </View>
            <Body style={{ fontSize: 11, lineHeight: 14, textAlign: 'center' }}>{s.text}</Body>
          </View>
        ))}
      </Card>
      <PaymentSetup onSaved={(me) => { setMe(me); done(); }} />
      {!returnTo ? (
        <>
          <TextLink label="Add later" color={colors.muted} onPress={done} />
          <Muted style={{ textAlign: 'center', marginTop: -10 }}>
            You'll need a payment method before booking.
          </Muted>
        </>
      ) : null}
    </Screen>
  );
}

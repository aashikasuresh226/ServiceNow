/**
 * Last step before matching: confirm where the technician should go.
 * Matching picks the qualified technician who can arrive soonest (see backend
 * domain/matching.py): closest + available + qualified for this unit.
 */
import { router, useLocalSearchParams } from 'expo-router';
import { View } from 'react-native';
import Svg, { Circle, Path, Rect } from 'react-native-svg';

import { decorative } from '@/components/a11y';
import { Icon } from '@/components/icons';
import { colors } from '@/components/theme';
import { Body, Button, Card, ErrorText, Muted, Row, Screen, StepHeader, TextLink, Title } from '@/components/ui';
import { api } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { useAction, useOptions } from '@/lib/hooks';

export default function ConfirmAddress() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const options = useOptions();
  const { me } = useAuth();

  const find = useAction(async () => {
    await api.match(id);
    router.replace(`/request/${id}`);
  });

  return (
    <Screen footer={<Button label="Find a technician" icon="sparkle" busy={find.busy}
      onPress={() => find.run()} />}>
      <StepHeader step={4} />
      <Title sub="We'll send the qualified technician who can get to you soonest.">Where should they go?</Title>
      <Card style={{ flexDirection: 'row', alignItems: 'center', padding: 0, overflow: 'hidden', gap: 0 }}>
        <Svg width={72} height={64} viewBox="0 0 64 56" {...decorative}>
          <Rect width={64} height={56} fill="#E9ECF0" />
          <Rect x={38} y={4} width={22} height={18} rx={3} fill="#DCE8DA" />
          <Path d="M0 34H64M22 0V56" stroke="#FFFFFF" strokeWidth={5} />
          <Path d="M32 40s-7-6-7-11a7 7 0 0 1 14 0c0 5-7 11-7 11z" fill={colors.primary} />
          <Circle cx={32} cy={29} r={2.5} fill="#FFFFFF" />
        </Svg>
        <View style={{ flex: 1, paddingHorizontal: 12 }}>
          <Muted>Service address</Muted>
          <Body numberOfLines={2}>{me?.address ?? '—'}</Body>
        </View>
        <View style={{ paddingRight: 12 }}>
          <TextLink label="Change" onPress={() => router.push('/profile')} />
        </View>
      </Card>
      <Card tone="muted" style={{ gap: 8 }}>
        {[
          ['shield', 'Qualified for your unit (and EPA 608 certified for refrigerant work)'],
          ['mapPin', 'Closest to your home'],
          ['clock', "Free now, or the earliest opening on their calendar if everyone's busy"],
        ].map(([icon, text]) => (
          <Row key={text} style={{ alignItems: 'flex-start' }}>
            <Icon name={icon as 'shield'} size={16} color={colors.primary} />
            <Muted style={{ flex: 1 }}>{text}</Muted>
          </Row>
        ))}
      </Card>
      {options?.features.payments && !me?.payment_method_label ? (
        <Row>
          <Muted style={{ flex: 1 }}>You'll need a payment method to confirm a booking.</Muted>
          <TextLink label="Add" onPress={() => router.push({ pathname: '/payment', params: { returnTo: `/request/${id}/preferences` } })} />
        </Row>
      ) : null}
      <ErrorText message={find.error} />
    </Screen>
  );
}

import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';
import Svg, { Circle, Path, Rect } from 'react-native-svg';

import { OPTION_ICONS } from '@/components/icons';
import { colors } from '@/components/theme';
import { Body, Button, Card, Checkbox, ErrorText, Loading, Muted, Row, Screen, StepHeader, TextLink, Title, Tile } from '@/components/ui';
import { api } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { useAction, useOptions } from '@/lib/hooks';
import { decorative } from '@/components/a11y';

export default function Preferences() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const options = useOptions();
  const { me } = useAuth();
  const [skills, setSkills] = useState<string[]>([]);
  const [requireAll, setRequireAll] = useState(false);

  const find = useAction(async () => {
    await api.setPreferences(id, skills, requireAll);
    await api.match(id);
    router.replace(`/request/${id}`);
  });

  if (!options) return <Loading />;
  const toggle = (v: string) => setSkills((s) => (s.includes(v) ? s.filter((x) => x !== v) : [...s, v]));

  return (
    <Screen footer={<Button label="Find a technician" icon="sparkle" busy={find.busy}
      onPress={() => find.run()} />}>
      <StepHeader step={4} />
      <Title sub="Optional. We'll favor technicians who match.">Your ideal tech</Title>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
        {options.soft_skills.map((o) => (
          <Tile key={o.value} label={o.label} icon={OPTION_ICONS[o.value] ?? 'star'}
            selected={skills.includes(o.value)} onPress={() => toggle(o.value)} />
        ))}
      </View>
      {skills.length ? (
        <Checkbox label="Must match all my picks" checked={requireAll} onChange={setRequireAll}
          hint="Off: closest qualified tech, your picks break ties" />
      ) : null}
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
      {!me?.payment_method_label ? (
        <Row>
          <Muted style={{ flex: 1 }}>You'll need a payment method to confirm a booking.</Muted>
          <TextLink label="Add" onPress={() => router.push({ pathname: '/payment', params: { returnTo: `/request/${id}/preferences` } })} />
        </Row>
      ) : null}
      <ErrorText message={find.error} />
    </Screen>
  );
}

import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { Text, View } from 'react-native';

import { Icon } from '@/components/icons';
import { EstimateBar } from '@/components/illustrations';
import { colors } from '@/components/theme';
import { Body, Button, Card, Loading, Muted, Row, Screen, StepHeader, TextLink, Title } from '@/components/ui';
import { api } from '@/lib/api';
import { money } from '@/lib/format';
import type { ServiceRequest } from '@/lib/types';

export default function Estimate() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const [request, setRequest] = useState<ServiceRequest | null>(null);

  useEffect(() => {
    api.getRequest(id).then(setRequest).catch(() => undefined);
  }, [id]);

  if (!request) return <Loading />;
  const { diagnostic_fee_cents: fee, low_cents: low } = request.estimate;
  const repair = low != null && fee != null ? low - fee : null;

  return (
    <Screen footer={
      <>
        <Button label="Continue" onPress={() => router.push(`/request/${id}/preferences`)} />
        <TextLink label="Save for later" color={colors.muted} onPress={() => router.replace('/home')} />
      </>
    }>
      <StepHeader step={3} />
      <Title>Estimated cost</Title>
      <Card style={{ alignItems: 'center', gap: 6, paddingVertical: 20 }}>
        <Muted>Starting from</Muted>
        <Text style={{ fontSize: 44, fontWeight: '800', color: colors.ink, letterSpacing: -1 }}>
          {money(low)}
        </Text>
        <Muted>for {request.diagnosis?.primary_issue_label.toLowerCase() ?? 'the visit'}</Muted>
        <View style={{ alignSelf: 'stretch', gap: 4, marginTop: 8 }}>
          <EstimateBar />
          <Row style={{ justifyContent: 'space-between' }}>
            <Muted style={{ fontSize: 11 }}>Estimate</Muted>
            <Muted style={{ fontSize: 11 }}>Final price set on site</Muted>
          </Row>
        </View>
      </Card>
      <Row style={{ gap: 10 }}>
        <Card tone="muted" style={{ flex: 1 }}>
          <Icon name="truck" size={20} color={colors.ink} />
          <Muted>Diagnostic visit</Muted>
          <Body style={{ fontWeight: '700' }}>{money(fee)}</Body>
        </Card>
        <Card tone="muted" style={{ flex: 1 }}>
          <Icon name="wrench" size={20} color={colors.ink} />
          <Muted>Likely repair</Muted>
          <Body style={{ fontWeight: '700' }}>{repair ? `from ${money(repair)}` : 'On site'}</Body>
        </Card>
      </Row>
      <Row style={{ alignItems: 'flex-start' }}>
        <Icon name="info" size={18} color={colors.muted} />
        <Muted style={{ flex: 1 }}>
          <Text style={{ fontWeight: '700', color: colors.body }}>This is only an estimate.</Text> It's
          the low end, based on your photo and description. Your technician confirms the final price
          before any work starts.
        </Muted>
      </Row>
    </Screen>
  );
}

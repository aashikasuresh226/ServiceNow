import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { Text, View } from 'react-native';

import { Icon } from '@/components/icons';
import { EstimateBar } from '@/components/illustrations';
import { colors } from '@/components/theme';
import { Body, Button, Card, Loading, Muted, Row, Screen, StepHeader, TextLink, Title } from '@/components/ui';
import { api } from '@/lib/api';
import { estimateRange, money } from '@/lib/format';
import type { ServiceRequest } from '@/lib/types';

export default function Estimate() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const [request, setRequest] = useState<ServiceRequest | null>(null);

  useEffect(() => {
    api.getRequest(id).then(setRequest).catch(() => undefined);
  }, [id]);

  if (!request) return <Loading />;
  const { diagnostic_fee_cents: fee, low_cents: low, high_cents: high, basis } = request.estimate;
  const repairLow = low != null && fee != null ? low - fee : null;
  const repairHigh = high != null && fee != null ? high - fee : null;
  const ranged = high != null && low != null && high > low;
  const repairText = repairLow
    ? repairHigh && repairHigh > repairLow ? `${money(repairLow)}–${money(repairHigh)}` : `from ${money(repairLow)}`
    : 'On site';

  if (request.estimate.source === 'visit_only') {
    // No problem identified: the visit has a price, the repair is quoted on site. No estimate.
    return (
      <Screen footer={
        <>
          <Button label="Continue" onPress={() => router.push(`/request/${id}/times`)} />
          <TextLink label="Save for later" color={colors.muted} onPress={() => router.replace('/home')} />
        </>
      }>
        <StepHeader step={3} />
        <Title sub="There's no repair estimate because the problem hasn't been identified yet.">What it costs</Title>
        <Card style={{ gap: 10 }}>
          <Row style={{ justifyContent: 'space-between' }}>
            <Row><Icon name="truck" size={20} color={colors.ink} /><Body>Diagnostic visit</Body></Row>
            <Body style={{ fontWeight: '700' }}>{money(fee)}</Body>
          </Row>
          <Row style={{ justifyContent: 'space-between' }}>
            <Row><Icon name="wrench" size={20} color={colors.ink} /><Body>Repair</Body></Row>
            <Muted>Priced on site</Muted>
          </Row>
        </Card>
        <Row style={{ alignItems: 'flex-start' }}>
          <Icon name="info" size={18} color={colors.muted} />
          <Muted style={{ flex: 1 }}>
            Your technician finds the problem and tells you the price in the app before any work starts. You approve it first.
          </Muted>
        </Row>
      </Screen>
    );
  }

  return (
    <Screen footer={
      <>
        <Button label="Continue" onPress={() => router.push(`/request/${id}/times`)} />
        <TextLink label="Save for later" color={colors.muted} onPress={() => router.replace('/home')} />
      </>
    }>
      <StepHeader step={3} />
      <Title>Estimated cost</Title>
      <Card style={{ alignItems: 'center', gap: 6, paddingVertical: 20 }}>
        <Muted>{ranged ? 'Likely total' : 'Starting from'}</Muted>
        <Text style={{ fontSize: ranged ? 38 : 44, fontWeight: '800', color: colors.ink, letterSpacing: -1 }}
          adjustsFontSizeToFit numberOfLines={1}>
          {ranged ? estimateRange(request.estimate) : money(low)}
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
          <Body style={{ fontWeight: '700' }}>{repairText}</Body>
        </Card>
      </Row>
      <Row style={{ alignItems: 'flex-start' }}>
        <Icon name="info" size={18} color={colors.muted} />
        <Muted style={{ flex: 1 }}>
          <Text style={{ fontWeight: '700', color: colors.body }}>This is only an estimate.</Text>{' '}
          {basis ?? 'Based on your photo and description.'} Your technician confirms the final price
          before any work starts.
        </Muted>
      </Row>
    </Screen>
  );
}

/** A job from the company's Housecall Pro: details, call and directions. It's run (started,
 * invoiced, completed) in Housecall Pro; this view refreshes from it every minute. */
import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { Linking, Platform, Text } from 'react-native';

import { Icon } from '@/components/icons';
import { colors } from '@/components/theme';
import { Badge, Body, Button, Card, Loading, Muted, Row, Screen, StepHeader, Title } from '@/components/ui';
import { techApi } from '@/lib/api';
import { visitTime } from '@/lib/format';
import type { OutsideJob } from '@/lib/types';

function goToday() {
  if (router.canGoBack()) router.dismissTo('/tech');
  else router.replace('/tech');
}

export default function OutsideJobScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const [job, setJob] = useState<OutsideJob | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    techApi.outsideJob(id).then(setJob).catch(() => setError('This job is no longer assigned to you.'));
  }, [id]);

  if (error) {
    return (
      <Screen footer={<Button label="Back to today" onPress={goToday} />}>
        <StepHeader onBack={goToday} />
        <Card tone="muted"><Muted>{error}</Muted></Card>
      </Screen>
    );
  }
  if (!job) return <Loading />;
  const directions = job.address
    ? (Platform.OS === 'ios' ? 'http://maps.apple.com/?daddr=' : 'https://www.google.com/maps/dir/?api=1&destination=')
      + encodeURIComponent(job.address)
    : null;
  return (
    <Screen>
      <StepHeader onBack={goToday} />
      <Row style={{ justifyContent: 'space-between' }}>
        <Badge label="Housecall Pro" tone="neutral" />
        {job.starts_at ? <Muted>{visitTime(job.starts_at)}</Muted> : <Muted>Not scheduled yet</Muted>}
      </Row>
      <Title sub={job.address ?? 'No address on the job'}>{job.customer_name ?? 'Customer'}</Title>
      <Row style={{ gap: 8 }}>
        {job.customer_phone ? (
          <Button label="Call" variant="secondary" icon="phone" style={{ flex: 1 }}
            accessibilityLabel={`Call ${job.customer_name ?? 'customer'}`}
            onPress={() => Linking.openURL(`tel:${job.customer_phone}`)} />
        ) : null}
        {directions ? (
          <Button label="Directions" variant="secondary" icon="navigation" style={{ flex: 1 }}
            onPress={() => Linking.openURL(directions)} />
        ) : null}
      </Row>
      <Card style={{ gap: 6 }}>
        <Text style={{ fontSize: 12, fontWeight: '700', color: colors.muted, textTransform: 'uppercase' }}>Job</Text>
        <Body>{job.description ?? 'No description'}</Body>
        <Muted>
          {[job.invoice_number ? `Job #${job.invoice_number}` : null, job.work_status || null].filter(Boolean).join(' · ')}
        </Muted>
      </Card>
      <Row style={{ alignItems: 'flex-start' }}>
        <Icon name="info" size={18} color={colors.muted} />
        <Muted style={{ flex: 1 }}>
          Booked in your company's Housecall Pro. Start, invoice and finish it there as usual; changes show up here within a minute.
          {job.customer_uses_app ? ' This customer uses the app too.' : ''}
        </Muted>
      </Row>
    </Screen>
  );
}

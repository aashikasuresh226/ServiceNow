import { router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Icon } from '@/components/icons';
import { AcUnit, HouseIllustration } from '@/components/illustrations';
import { colors } from '@/components/theme';
import { Badge, Body, Button, Card, Label, Muted, Row, Screen } from '@/components/ui';
import { api } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { labelFor, useOptions } from '@/lib/hooks';
import type { ServiceRequest } from '@/lib/types';

const ACTIVE = new Set(['proposed', 'waitlisted', 'offered', 'dispatched', 'en_route', 'on_site',
  'quoted', 'in_progress']);

const STATUS_LABEL: Record<string, string> = {
  draft: 'Draft',
  analyzed: 'Ready to book',
  proposed: 'Tech found',
  waitlisted: 'On waitlist',
  offered: 'Confirming',
  dispatched: 'Booked',
  en_route: 'On the way',
  on_site: 'On site',
  quoted: 'Approve price',
  in_progress: 'In progress',
  completed: 'Completed',
  canceled: 'Canceled',
};

export default function Home() {
  const { me } = useAuth();
  const options = useOptions();
  const [requests, setRequests] = useState<ServiceRequest[]>([]);

  useFocusEffect(
    useCallback(() => {
      api.listRequests().then(setRequests).catch(() => undefined);
    }, []),
  );

  const active = requests.find((r) => ACTIVE.has(r.status));
  const firstName = me?.name?.split(' ')[0];
  const lastUnit = requests.find((r) => r.unit?.brand)?.unit;

  const openRequest = (r: ServiceRequest) => {
    if (r.status === 'draft') router.push(`/request/${r.id}/photo`);
    else if (r.status === 'analyzed') router.push(`/request/${r.id}/diagnosis`);
    else router.push(`/request/${r.id}`);
  };

  return (
    <Screen
      footer={
        <View style={styles.tabs} accessibilityRole="tablist">
          <Tab icon="home" label="Home" active />
          <Tab icon="user" label="Account" onPress={() => router.push('/account')} />
        </View>
      }
    >
      <Row style={{ justifyContent: 'space-between' }}>
        <Text style={styles.hello} accessibilityRole="header">
          Hi{firstName ? ` ${firstName}` : ''}
        </Text>
      </Row>

      {active ? (
        <Pressable onPress={() => openRequest(active)} accessibilityRole="button">
          <Card tone="amber" style={{ flexDirection: 'row', alignItems: 'center' }}>
            <Icon name="truck" size={22} color={colors.amberInk} />
            <View style={{ flex: 1 }}>
              <Body style={{ fontWeight: '700' }}>{STATUS_LABEL[active.status]}</Body>
              <Muted>
                {active.technician ? `${active.technician.name} · ${active.technician.shop_name}`
                  : 'Tap to see live status'}
              </Muted>
            </View>
            <Icon name="chevronRight" size={20} color={colors.amberInk} />
          </Card>
        </Pressable>
      ) : null}

      <Card tone="soft" style={{ alignItems: 'center', gap: 12 }}>
        <HouseIllustration width={230} />
        <Text style={styles.cta}>HVAC trouble? Get help fast.</Text>
        <Button label="Start a request" style={{ alignSelf: 'stretch' }}
          onPress={() => router.push('/request/new')} />
      </Card>

      <Label>Your units</Label>
      <Row style={{ gap: 10 }}>
        <Card style={styles.unitCard}>
          <AcUnit width={64} />
          <Muted style={{ fontWeight: '600', color: colors.ink, textAlign: 'center' }}>
            {lastUnit ? `${lastUnit.brand} ${labelFor(options, 'equipment_types', lastUnit.equipment_type)}`
              : 'Added after your first request'}
          </Muted>
        </Card>
      </Row>

      {requests.length ? <Label>Recent requests</Label> : null}
      {requests.slice(0, 5).map((r) => (
        <Pressable key={r.id} onPress={() => openRequest(r)} accessibilityRole="button">
          <Row style={styles.historyRow}>
            <View style={{ flex: 1 }}>
              <Body style={{ fontWeight: '600' }}>
                {r.diagnosis?.primary_issue_label
                  ?? r.symptoms.map((s) => labelFor(options, 'symptoms', s)).join(', ')}
              </Body>
              <Muted>{new Date(r.created_at).toLocaleDateString()}</Muted>
            </View>
            <Badge label={STATUS_LABEL[r.status] ?? r.status}
              tone={r.status === 'completed' ? 'success' : ACTIVE.has(r.status) ? 'amber' : 'neutral'} />
          </Row>
        </Pressable>
      ))}
    </Screen>
  );
}

function Tab({ icon, label, active, onPress }: {
  icon: 'home' | 'user';
  label: string;
  active?: boolean;
  onPress?: () => void;
}) {
  const color = active ? colors.primary : colors.muted;
  return (
    <Pressable accessibilityRole="tab" accessibilityState={{ selected: !!active }} onPress={onPress}
      style={styles.tab}>
      <Icon name={icon} size={22} color={color} />
      <Text style={{ fontSize: 11, fontWeight: active ? '700' : '500', color }}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  hello: { fontSize: 26, fontWeight: '800', color: colors.ink, letterSpacing: -0.4 },
  cta: { fontSize: 17, fontWeight: '700', color: colors.ink },
  unitCard: { width: 150, alignItems: 'center', gap: 6 },
  historyRow: { paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: colors.line },
  tabs: { flexDirection: 'row', justifyContent: 'space-around' },
  tab: { alignItems: 'center', gap: 2, minWidth: 64, minHeight: 44, justifyContent: 'center' },
});

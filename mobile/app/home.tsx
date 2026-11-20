import { router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Linking, Pressable, StyleSheet, Text, View } from 'react-native';

import { Icon } from '@/components/icons';
import { HouseIllustration } from '@/components/illustrations';
import { colors } from '@/components/theme';
import { Badge, Body, Button, Card, Label, Muted, Row, Screen } from '@/components/ui';
import { api } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { useUnread } from '@/lib/unread';
import { labelFor, useOptions } from '@/lib/hooks';
import type { HomeVisit, ServiceRequest } from '@/lib/types';

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
  const [visits, setVisits] = useState<HomeVisit[]>([]);

  useFocusEffect(
    useCallback(() => {
      api.listRequests().then(setRequests).catch(() => undefined);
      api.visits().then(setVisits).catch(() => undefined);
      // Visits booked by the company can change (on the way, rescheduled): keep them fresh.
      const timer = setInterval(() => { api.visits().then(setVisits).catch(() => undefined); }, 15000);
      return () => clearInterval(timer);
    }, []),
  );

  const { byRequest } = useUnread();
  const active = requests.find((r) => ACTIVE.has(r.status));
  const newFor = (r: ServiceRequest) => byRequest[r.id] ?? 0;
  const firstName = me?.name?.split(' ')[0];

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
            {newFor(active) ? <NewBadge count={newFor(active)} /> : null}
            <Icon name="chevronRight" size={20} color={colors.amberInk} />
          </Card>
        </Pressable>
      ) : null}

      {visits.map((v) => <VisitCard key={v.id} visit={v} />)}

      <Card tone="soft" style={{ alignItems: 'center', gap: 12 }}>
        <HouseIllustration width={230} />
        <Text style={styles.cta}>HVAC trouble? Get help fast.</Text>
        <Button label="Start a request" style={{ alignSelf: 'stretch' }}
          onPress={() => router.push('/request/new')} />
      </Card>

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
            {newFor(r) && r.id !== active?.id ? <NewBadge count={newFor(r)} /> : null}
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
  historyRow: { paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: colors.line },
  tabs: { flexDirection: 'row', justifyContent: 'space-around' },
  tab: { alignItems: 'center', gap: 2, minWidth: 64, minHeight: 44, justifyContent: 'center' },
});

function NewBadge({ count }: { count: number }) {
  return (
    <View accessibilityLabel={`${count} new message${count === 1 ? '' : 's'}`}
      style={{ flexDirection: 'row', alignItems: 'center', gap: 4, backgroundColor: colors.primary,
        borderRadius: 999, paddingHorizontal: 8, paddingVertical: 3 }}>
      <Icon name="chat" size={12} color="#fff" />
      <Text style={{ color: '#fff', fontWeight: '700', fontSize: 12 }}>{count}</Text>
    </View>
  );
}

const VISIT_STATUS: Record<HomeVisit['status'], string> = {
  scheduled: 'Scheduled',
  en_route: 'On the way',
  on_site: 'Arrived',
  working: 'Working on it',
  finished: 'Finished',
};

/** A visit your company booked for you (in their Housecall Pro), shown here too. */
function VisitCard({ visit }: { visit: HomeVisit }) {
  const when = visit.starts_at
    ? new Date(visit.starts_at).toLocaleString([], { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
    : 'Time to be confirmed';
  const live = visit.status !== 'scheduled';
  return (
    <Card tone={live ? 'amber' : 'plain'} style={{ gap: 6 }}>
      <Row style={{ justifyContent: 'space-between' }}>
        <Body style={{ fontWeight: '700' }}>Visit from {visit.shop_name}</Body>
        <Badge label={VISIT_STATUS[visit.status]} tone={live ? 'amber' : 'neutral'} />
      </Row>
      <Muted>{when}{visit.technician_first_name ? ` · ${visit.technician_first_name}` : ''}</Muted>
      {visit.description ? <Muted numberOfLines={2}>{visit.description}</Muted> : null}
      {visit.shop_phone ? (
        <Button label={`Call ${visit.shop_name}`} variant="secondary" icon="phone"
          onPress={() => Linking.openURL(`tel:${visit.shop_phone}`)} />
      ) : null}
    </Card>
  );
}

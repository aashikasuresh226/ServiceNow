/**
 * Last step before matching: who should come, and where.
 * - Soonest available: the qualified technician who can arrive first (default).
 * - A company: the soonest technician from that company.
 * - A technician: that person, at their earliest opening.
 * Each choice shows its earliest arrival time, from the same scheduling engine.
 */
import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Icon } from '@/components/icons';
import { Avatar } from '@/components/illustrations';
import { colors } from '@/components/theme';
import { Body, Button, Card, ErrorText, Loading, Muted, Row, Screen, Segmented, StepHeader, TextLink, Title } from '@/components/ui';
import { api } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { takeChoice, type PendingChoice } from '@/lib/choice';
import { miles, visitTime } from '@/lib/format';
import { labelFor, useAction, useOptions } from '@/lib/hooks';
import type { Providers } from '@/lib/types';

type Mode = 'soonest' | 'shop' | 'technician';

export default function ChooseProvider() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const options = useOptions();
  const { me } = useAuth();
  const [providers, setProviders] = useState<Providers | null>(null);
  const [mode, setMode] = useState<Mode>('soonest');
  const [picked, setPicked] = useState<string | null>(null);
  // A company/technician from a shared link who can't take this request.
  const [unavailable, setUnavailable] = useState<PendingChoice | null>(null);

  const load = useAction(async () => {
    const [list, pending] = await Promise.all([api.providers(id), takeChoice()]);
    setProviders(list);
    if (pending) {
      const available = pending.kind === 'shop'
        ? list.shops.some((s) => s.id === pending.id)
        : list.technicians.some((t) => t.id === pending.id);
      if (available) {
        setMode(pending.kind);
        setPicked(pending.id);
      } else {
        setUnavailable(pending);
      }
    }
  });
  useEffect(() => { void load.run(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  const find = useAction(async () => {
    const choice = mode === 'shop' && picked ? { shop_id: picked }
      : mode === 'technician' && picked ? { technician_id: picked } : undefined;
    await api.match(id, choice);
    router.replace(`/request/${id}`);
  });

  if (!providers && !load.error) return <Loading label="Finding technicians near you" />;
  const shops = providers?.shops ?? [];
  const techs = providers?.technicians ?? [];
  const pickedName = mode === 'shop' ? shops.find((s) => s.id === picked)?.name
    : mode === 'technician' ? techs.find((t) => t.id === picked)?.name : undefined;
  const needsPick = mode !== 'soonest' && !picked;

  return (
    <Screen footer={
      <Button label={pickedName ? `Book ${pickedName.split(' ')[0]}` : 'Find a technician'}
        icon="sparkle" busy={find.busy} disabled={needsPick} onPress={() => find.run()} />
    }>
      <StepHeader step={4} />
      <Title sub="Pick someone you know, or we'll send whoever can get there soonest.">Who should come?</Title>
      <Segmented value={mode} onChange={(v) => { setMode(v as Mode); setPicked(null); }}
        options={[
          { value: 'soonest', label: 'Soonest' },
          { value: 'shop', label: 'Company' },
          { value: 'technician', label: 'Technician' },
        ]} />

      {unavailable ? (
        <Card tone="amber">
          <Body style={{ color: colors.amberInk }}>
            {unavailable.name} can't take this request (not taking requests, not qualified for
            this unit, outside their service area, or fully booked this week).
          </Body>
        </Card>
      ) : null}

      {mode === 'soonest' ? (
        <Card tone="muted" style={{ gap: 8 }}>
          {[
            ['shield', 'Qualified for your unit (and EPA 608 certified for refrigerant work)'],
            ['mapPin', 'Closest to your home'],
            ['clock', techs[0] ? `Earliest arrival right now: ${visitTime(techs[0].arrival_at)}`
              : "Free now, or the earliest opening on their calendar"],
          ].map(([icon, text]) => (
            <Row key={text} style={{ alignItems: 'flex-start' }}>
              <Icon name={icon as 'shield'} size={16} color={colors.primary} />
              <Muted style={{ flex: 1 }}>{text}</Muted>
            </Row>
          ))}
        </Card>
      ) : null}

      {mode === 'shop' ? (
        shops.length ? shops.map((s) => (
          <Choice key={s.id} selected={picked === s.id} onPress={() => setPicked(s.id)}
            label={`${s.name}, earliest ${visitTime(s.arrival_at)}`}>
            <View style={styles.shopMark}><Icon name="building" size={20} color={colors.primary} /></View>
            <View style={{ flex: 1, gap: 2 }}>
              <Text style={styles.name}>{s.name}</Text>
              <Muted>{stars(s.rating, s.rating_count)} · {miles(s.distance_km)} · {s.technician_count} available</Muted>
              <Muted>Earliest: {visitTime(s.arrival_at)}</Muted>
            </View>
          </Choice>
        )) : <Muted>No companies nearby can take this request right now.</Muted>
      ) : null}

      {mode === 'technician' ? (
        techs.length ? techs.map((t) => (
          <Choice key={t.id} selected={picked === t.id} onPress={() => setPicked(t.id)}
            label={`${t.name} from ${t.shop_name}, earliest ${visitTime(t.arrival_at)}`}>
            <Avatar size={44} name={t.name} />
            <View style={{ flex: 1, gap: 2 }}>
              <Text style={styles.name}>{t.name}</Text>
              <Muted>{t.shop_name} · {stars(t.rating, t.rating_count)} · {miles(t.distance_km)}</Muted>
              <Muted>
                Earliest: {visitTime(t.arrival_at)}
                {t.certifications.length ? ` · ${t.certifications.map((c) => labelFor(options, 'certifications', c)).join(', ')}` : ''}
              </Muted>
            </View>
          </Choice>
        )) : <Muted>No technicians nearby can take this request right now.</Muted>
      ) : null}

      <Card style={{ flexDirection: 'row', alignItems: 'center' }}>
        <Icon name="mapPin" size={18} color={colors.primary} />
        <View style={{ flex: 1 }}>
          <Muted>Service address</Muted>
          <Body numberOfLines={2}>{me?.address ?? '—'}</Body>
        </View>
        <TextLink label="Change" onPress={() => router.push('/profile')} />
      </Card>
      {options?.features.payments && !me?.payment_method_label ? (
        <Row>
          <Muted style={{ flex: 1 }}>You'll need a payment method to confirm a booking.</Muted>
          <TextLink label="Add" onPress={() => router.push({ pathname: '/payment', params: { returnTo: `/request/${id}/preferences` } })} />
        </Row>
      ) : null}
      <ErrorText message={load.error ?? find.error} />
    </Screen>
  );
}

function stars(rating: number | null, count: number): string {
  return rating ? `★ ${rating.toFixed(1)} (${count})` : 'New';
}

function Choice({ selected, onPress, label, children }: {
  selected: boolean; onPress: () => void; label: string; children: React.ReactNode;
}) {
  return (
    <Pressable accessibilityRole="radio" accessibilityState={{ checked: selected }}
      accessibilityLabel={label} onPress={onPress}
      style={[styles.choice, selected && styles.choiceSelected]}>
      {children}
      <View style={[styles.radio, selected && styles.radioOn]}>
        {selected ? <Icon name="check" size={12} color="#FFF" strokeWidth={3} /> : null}
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  choice: {
    flexDirection: 'row', alignItems: 'center', gap: 12, padding: 12, borderRadius: 14,
    borderWidth: 1.5, borderColor: colors.line, backgroundColor: '#FFFFFF',
  },
  choiceSelected: { borderColor: colors.primary, backgroundColor: colors.primarySoft },
  name: { fontSize: 16, fontWeight: '700', color: colors.ink },
  shopMark: {
    width: 44, height: 44, borderRadius: 12, backgroundColor: colors.primarySoft,
    alignItems: 'center', justifyContent: 'center',
  },
  radio: {
    width: 22, height: 22, borderRadius: 11, borderWidth: 1.5, borderColor: colors.lineStrong,
    alignItems: 'center', justifyContent: 'center',
  },
  radioOn: { backgroundColor: colors.primary, borderColor: colors.primary },
});

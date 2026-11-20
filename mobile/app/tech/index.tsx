/** Technician home: new offers (if allowed) and today's jobs (full day or next job only). */
import { router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Linking, Pressable, StyleSheet, Text, View } from 'react-native';

import { Icon } from '@/components/icons';
import { colors, radius } from '@/components/theme';
import { Badge, Body, Button, Card, Loading, Muted, Row, Screen, TextLink, Title } from '@/components/ui';
import { techApi } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { countdown, money, visitTime } from '@/lib/format';
import { labelFor, useCountdown, useOptions, usePolling } from '@/lib/hooks';
import { JOB_STATUS } from '@/lib/techStatus';
import type { OutsideJob, TechBoard, TechJob } from '@/lib/types';


export default function TechHome() {
  const { tech, signOutTech: signOut, refreshTech } = useAuth();
  const [board, setBoard] = useState<TechBoard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refresh = useCallback(async () => {
    try {
      // Permissions can change at any time (the company edits them), so refresh both.
      const [next] = await Promise.all([techApi.board(), refreshTech()]);
      setBoard(next);
      setError(null);
    } catch {
      setError("Couldn't refresh. Retrying…");
    }
  }, [refreshTech]);
  // Refresh whenever this screen comes back into view, and every few seconds while open.
  useFocusEffect(useCallback(() => { void refresh(); }, [refresh]));
  usePolling(refresh, 5000, true);

  if (!board || !tech) return <Loading label={error ?? undefined} />;
  const today = new Date().toLocaleDateString([], { weekday: 'long', month: 'short', day: 'numeric' });
  return (
    <Screen>
      <Row style={{ justifyContent: 'space-between' }}>
        <Muted>{tech.shop_name}</Muted>
        <TextLink label="Sign out" color={colors.muted} onPress={() => { void signOut().then(() => router.replace('/tech/sign-in')); }} />
      </Row>
      <Title sub={today}>{tech.schedule_view === 'next' ? 'Your next job' : `Hi ${tech.name.split(' ')[0]}`}</Title>

      {board.offers.length ? (
        <View style={{ gap: 8 }}>
          <Text style={styles.section}>New job offers</Text>
          {board.offers.map((job) => <OfferRow key={job.id} job={job} />)}
        </View>
      ) : null}

      <View style={{ gap: 8 }}>
        <Text style={styles.section}>{tech.schedule_view === 'next' ? 'Next' : 'Today and upcoming'}</Text>
        {board.jobs.length || board.outside_jobs.length ? byTime(board).map((item, i) => (
          'provider' in item
            ? <OutsideRow key={item.id} job={item} highlight={i === 0} />
            : <JobRow key={item.id} job={item} highlight={i === 0} />
        )) : (
          <Card tone="muted"><Muted>No jobs right now. New jobs appear here automatically.</Muted></Card>
        )}
        {board.hidden_jobs ? (
          <Card tone="muted" style={{ alignItems: 'center' }}>
            <Icon name="lock" size={18} color={colors.muted} />
            <Muted style={{ textAlign: 'center' }}>Your next job appears when you finish this one. {tech.shop_name} manages the rest of your day.</Muted>
          </Card>
        ) : null}
      </View>

      {board.recent.length ? (
        <View style={{ gap: 8 }}>
          <Text style={styles.section}>Recently completed</Text>
          {board.recent.map((job) => (
            <Row key={job.id} style={{ justifyContent: 'space-between' }}>
              <Muted>{job.customer_name ?? 'Customer'} · {job.diagnosis?.primary_issue_label ?? 'Service'}</Muted>
              <Body style={{ fontWeight: '600' }}>{money(job.quote?.final_price_cents)}</Body>
            </Row>
          ))}
        </View>
      ) : null}

      {tech.shop_phone ? (
        <Button label={`Call ${tech.shop_name}`} variant="secondary" icon="phone"
          onPress={() => Linking.openURL(`tel:${tech.shop_phone}`)} />
      ) : null}
    </Screen>
  );
}

/** Our jobs (started ones first) and the company's Housecall Pro jobs, by time. */
function byTime(board: TechBoard): (TechJob | OutsideJob)[] {
  const when = (item: TechJob | OutsideJob) => {
    const at = 'provider' in item ? item.starts_at : item.arrival_at;
    return at ? new Date(at).getTime() : Number.MAX_SAFE_INTEGER;
  };
  const started = board.jobs.filter((j) => j.status !== 'dispatched');
  const rest = [...board.jobs.filter((j) => j.status === 'dispatched'), ...board.outside_jobs];
  return [...started, ...rest.sort((a, b) => when(a) - when(b))];
}

const OUTSIDE_STATUS: Record<string, string> = {
  en_route: 'On the way', on_site: 'On site', working: 'Working', finished: 'Finished',
};

function OutsideRow({ job, highlight }: { job: OutsideJob; highlight: boolean }) {
  return (
    <Pressable accessibilityRole="button" onPress={() => router.push(`/tech/outside/${job.id}`)}
      style={[styles.row, highlight && { borderColor: colors.primary, backgroundColor: colors.primarySoft }]}>
      <View style={{ width: 64 }}>
        <Text style={{ fontWeight: '700', color: colors.ink }}>
          {job.starts_at ? new Date(job.starts_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }) : '—'}
        </Text>
      </View>
      <View style={{ flex: 1, gap: 2 }}>
        <Body style={{ fontWeight: '700' }}>{job.customer_name ?? 'Customer'}</Body>
        <Muted numberOfLines={1}>{job.address ?? job.description ?? ''}</Muted>
        {job.starts_at && new Date(job.starts_at).toDateString() !== new Date().toDateString()
          ? <Muted>{visitTime(job.starts_at)}</Muted> : null}
      </View>
      <View style={{ alignItems: 'flex-end', gap: 4 }}>
        <Badge label="Housecall Pro" tone="neutral" />
        {job.app_status ? (
          <Badge label={OUTSIDE_STATUS[job.app_status] ?? job.app_status} tone={job.app_status === 'finished' ? 'success' : 'amber'} />
        ) : null}
      </View>
    </Pressable>
  );
}

function OfferRow({ job }: { job: TechJob }) {
  const options = useOptions();
  const seconds = useCountdown(job.offer_expires_at);
  return (
    <Pressable accessibilityRole="button" onPress={() => router.push(`/tech/job/${job.id}`)}
      style={[styles.row, { borderColor: colors.amberInk, backgroundColor: colors.amberSoft }]}>
      <View style={{ flex: 1, gap: 2 }}>
        <Body style={{ fontWeight: '700' }}>
          {job.symptoms.map((s) => labelFor(options, 'symptoms', s)).join(', ') || 'Service request'}
        </Body>
        <Muted>{job.area_label}{job.arrival_at ? ` · ${visitTime(job.arrival_at)}` : ''}</Muted>
      </View>
      <Badge label={seconds != null ? `Reply ${countdown(seconds)}` : 'New'} tone="amber" />
    </Pressable>
  );
}

function JobRow({ job, highlight }: { job: TechJob; highlight: boolean }) {
  const [label, tone] = JOB_STATUS[job.status] ?? [job.status, 'neutral'];
  return (
    <Pressable accessibilityRole="button" onPress={() => router.push(`/tech/job/${job.id}`)}
      style={[styles.row, highlight && { borderColor: colors.primary, backgroundColor: colors.primarySoft }]}>
      <View style={{ width: 64 }}>
        <Text style={{ fontWeight: '700', color: colors.ink }}>
          {job.arrival_at ? new Date(job.arrival_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }) : '—'}
        </Text>
      </View>
      <View style={{ flex: 1, gap: 2 }}>
        <Body style={{ fontWeight: '700' }}>{job.customer_name ?? 'Customer'}</Body>
        <Muted numberOfLines={1}>{job.address ?? job.area_label}</Muted>
        {job.technician_flag ? <Muted style={{ color: colors.danger }}>You said you can't make it</Muted> : null}
      </View>
      <Badge label={label} tone={tone} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  section: { fontSize: 12, fontWeight: '700', color: colors.muted, textTransform: 'uppercase', letterSpacing: 0.6 },
  row: {
    flexDirection: 'row', alignItems: 'center', gap: 10, padding: 14, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.line, backgroundColor: colors.surface, minHeight: 64,
  },
});

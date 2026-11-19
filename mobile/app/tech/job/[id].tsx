/** One job for the technician: respond to the offer, drive (sharing location), quote, finish. */
import { router, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { Image, Linking, Platform, ScrollView, StyleSheet, Text, View } from 'react-native';

import { Icon } from '@/components/icons';
import { colors, radius } from '@/components/theme';
import { Badge, Body, Button, Card, ErrorText, Field, KeyValue, Loading, Muted, Row, Screen, StepHeader, TextLink, Title } from '@/components/ui';
import { techApi } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { countdown, money, visitTime } from '@/lib/format';
import { labelFor, useAction, useCountdown, useOptions, usePolling } from '@/lib/hooks';
import { useLiveLocation } from '@/lib/liveLocation';
import type { TechJob } from '@/lib/types';
import { JOB_STATUS } from '@/lib/techStatus';

/** Back to the existing "Today" screen instead of stacking a new one. */
function goToday() {
  if (router.canGoBack()) router.dismissTo('/tech');
  else router.replace('/tech');
}

export default function TechJobScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const [job, setJob] = useState<TechJob | null>(null);
  const [gone, setGone] = useState(false);
  const refresh = useCallback(async () => {
    try {
      setJob(await techApi.job(id));
    } catch {
      setGone(true); // declined, reassigned, or hidden by "next job only"
    }
  }, [id]);
  useEffect(() => { void refresh(); }, [refresh]);
  usePolling(refresh, 5000, !!job && job.status !== 'completed');
  const sharing = useLiveLocation(id, job?.status === 'en_route');

  if (gone && !job) {
    return (
      <Screen>
        <StepHeader onBack={() => goToday()} />
        <Title sub="It may have been reassigned or taken by someone else.">This job isn't available</Title>
        <Button label="Back to today" onPress={() => goToday()} />
      </Screen>
    );
  }
  if (!job) return <Loading />;
  return <JobView job={job} onChange={setJob} sharing={sharing} />;
}

function JobView({ job, onChange, sharing }: {
  job: TechJob;
  onChange: (j: TechJob) => void;
  sharing: ReturnType<typeof useLiveLocation>;
}) {
  const options = useOptions();
  const { tech } = useAuth();
  const [label, tone] = JOB_STATUS[job.status] ?? [job.status, 'neutral'];
  const act = useAction(async (fn: () => Promise<TechJob | void>) => {
    const next = await fn();
    if (next) onChange(next);
  });
  const directions = job.address
    ? (Platform.OS === 'ios' ? 'http://maps.apple.com/?daddr=' : 'https://www.google.com/maps/dir/?api=1&destination=')
      + encodeURIComponent(job.address)
    : null;

  return (
    <Screen footer={<Actions job={job} act={act} sharing={sharing} canRespond={!!tech?.can_respond_offers} />}>
      <StepHeader onBack={() => goToday()} />
      <Row style={{ justifyContent: 'space-between' }}>
        <Badge label={label} tone={tone} />
        {job.arrival_at ? <Muted>{visitTime(job.arrival_at)}</Muted> : null}
      </Row>
      <Title sub={job.address ?? `${job.area_label} · address shown after you accept`}>
        {job.customer_name ?? 'New customer'}
      </Title>

      {job.technician_flag ? (
        <Card tone="amber"><Body>You told the office you can't make this job: “{job.technician_flag}”. They'll reassign it or call you.</Body></Card>
      ) : null}

      {(job.can_contact && job.status !== 'offered') || directions ? (
        <Row style={{ gap: 8 }}>
          {job.chat_open ? (
            <Button label="Message" variant="secondary" icon="chat" style={{ flex: 1 }}
              onPress={() => router.push(`/tech/chat/${job.id}`)} />
          ) : null}
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
      ) : null}

      {job.status === 'en_route' ? <SharingNote state={sharing.state} name={job.customer_name} /> : null}

      <Card style={{ gap: 6 }}>
        <Text style={styles.cardTitle}>Problem</Text>
        <Body>{job.symptoms.map((s) => labelFor(options, 'symptoms', s)).join(', ') || 'See description'}</Body>
        {job.description ? <Muted>“{job.description}”</Muted> : null}
      </Card>
      <Card style={{ gap: 6 }}>
        <Row><Icon name="sparkle" size={14} color={colors.primary} /><Text style={styles.cardTitle}>From the photo</Text></Row>
        <KeyValue k="Unit" v={[job.unit?.brand, job.unit?.model_number].filter(Boolean).join(' ') || 'Unknown'} />
        {job.unit?.equipment_type ? <KeyValue k="Type" v={labelFor(options, 'equipment_types', job.unit.equipment_type)} /> : null}
        {job.unit?.approx_age_years != null ? <KeyValue k="Age" v={`~${job.unit.approx_age_years} years`} /> : null}
        {job.unit?.refrigerant ? <KeyValue k="Refrigerant" v={job.unit.refrigerant} /> : null}
        {job.diagnosis ? <Muted>Likely: {job.diagnosis.primary_issue_label}. {job.diagnosis.summary}</Muted> : null}
      </Card>
      {job.photos.length ? (
        <ScrollView horizontal contentContainerStyle={{ gap: 8 }}>
          {job.photos.map((p) => (
            <Image key={p.id} source={{ uri: p.url }} style={styles.photo} accessibilityLabel="Customer's photo of the unit" />
          ))}
        </ScrollView>
      ) : null}
      {job.quote ? (
        <Card tone="muted"><KeyValue k="Your price" v={money(job.quote.final_price_cents)} />
          {job.quote.notes ? <Muted>{job.quote.notes}</Muted> : null}</Card>
      ) : null}
      <ErrorText message={act.error} />
    </Screen>
  );
}

function SharingNote({ state, name }: { state: string; name: string | null }) {
  const text = {
    starting: 'Starting location sharing…',
    sharing: `${name ?? 'The customer'} can see your live location for this job. It stops when you tap Arrived.`,
    denied: 'Location is blocked. Allow location for this app so the customer can see you coming.',
    error: "Couldn't share your location. Check your connection; we'll keep trying.",
    off: '',
  }[state] ?? '';
  if (!text) return null;
  return (
    <Card tone={state === 'sharing' ? 'soft' : 'amber'}>
      <Row>
        {state === 'sharing' ? <View style={styles.liveDot} /> : <Icon name="alert" size={16} color={colors.amberInk} />}
        <Body style={{ flex: 1 }}>{text}</Body>
      </Row>
    </Card>
  );
}

function Actions({ job, act, sharing, canRespond }: {
  job: TechJob;
  act: ReturnType<typeof useAction<[() => Promise<TechJob | void>], void>>;
  sharing: ReturnType<typeof useLiveLocation>;
  canRespond: boolean;
}) {
  const seconds = useCountdown(job.offer_expires_at);
  const [reason, setReason] = useState('');
  const [asking, setAsking] = useState(false);
  const [price, setPrice] = useState('');
  const [notes, setNotes] = useState('');
  const cents = Math.round(parseFloat(price || '0') * 100);

  if (job.status === 'offered' && canRespond) {
    if (asking) {
      return (
        <View style={{ gap: 8 }}>
          <Field label="Reason (optional)" value={reason} onChangeText={setReason} placeholder="e.g. Too far today" />
          <Row style={{ gap: 8 }}>
            <Button label="Back" variant="secondary" style={{ flex: 1 }} onPress={() => setAsking(false)} />
            <Button label="Decline job" variant="danger" style={{ flex: 1 }} busy={act.busy}
              onPress={() => act.run(async () => { await techApi.decline(job.id, reason); goToday(); })} />
          </Row>
        </View>
      );
    }
    return (
      <View style={{ gap: 6 }}>
        {seconds != null ? <Muted style={{ textAlign: 'center' }}>Respond within {countdown(seconds)}</Muted> : null}
        <Row style={{ gap: 8 }}>
          <Button label="Decline" variant="secondary" style={{ flex: 1 }} onPress={() => setAsking(true)} />
          <Button label="Accept" style={{ flex: 1.4 }} busy={act.busy} onPress={() => act.run(() => techApi.accept(job.id))} />
        </Row>
      </View>
    );
  }
  if (job.status === 'dispatched') {
    if (asking) {
      return (
        <View style={{ gap: 8 }}>
          <Field label="Tell the office why" value={reason} onChangeText={setReason} placeholder="e.g. Truck broke down" />
          <Row style={{ gap: 8 }}>
            <Button label="Back" variant="secondary" style={{ flex: 1 }} onPress={() => setAsking(false)} />
            <Button label="Send to office" variant="danger" style={{ flex: 1 }} busy={act.busy}
              onPress={() => act.run(async () => { const next = await techApi.cantMakeIt(job.id, reason); setAsking(false); return next; })} />
          </Row>
        </View>
      );
    }
    return (
      <View style={{ gap: 6 }}>
        <Button label="Start driving" icon="navigation" busy={act.busy}
          onPress={() => act.run(() => techApi.startDriving(job.id))} />
        <Muted style={{ textAlign: 'center', fontSize: 12 }}>Shares your live location with this customer until you arrive.</Muted>
        {!canRespond && !job.technician_flag ? (
          <TextLink label="I can't make this one" color={colors.muted} onPress={() => setAsking(true)} />
        ) : null}
      </View>
    );
  }
  if (job.status === 'en_route') {
    return (
      <View style={{ gap: 6 }}>
        {sharing.lastSent ? <Muted style={{ textAlign: 'center', fontSize: 12 }}>Location sent {sharing.lastSent.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', second: '2-digit' })}</Muted> : null}
        <Button label="Arrived" icon="mapPin" busy={act.busy} onPress={() => act.run(() => techApi.arrived(job.id))} />
      </View>
    );
  }
  if (job.status === 'on_site') {
    return (
      <View style={{ gap: 8 }}>
        <Row style={{ gap: 8 }}>
          <View style={{ flex: 1 }}><Field label="Final price ($)" value={price} onChangeText={setPrice} keyboardType="decimal-pad" placeholder="185" /></View>
        </Row>
        <Field label="What you found / will do" value={notes} onChangeText={setNotes} placeholder="Replaced run capacitor" />
        <Button label="Send price to customer" busy={act.busy} disabled={cents <= 0}
          onPress={() => act.run(() => techApi.quote(job.id, cents, notes))} />
      </View>
    );
  }
  if (job.status === 'quoted') {
    return <Muted style={{ textAlign: 'center' }}>Waiting for the customer to approve {money(job.quote?.final_price_cents)} in their app…</Muted>;
  }
  if (job.status === 'in_progress') {
    return <Button label="Mark job complete" icon="check" busy={act.busy} onPress={() => act.run(() => techApi.complete(job.id))} />;
  }
  if (job.status === 'completed') {
    return <Button label="Back to today" variant="secondary" onPress={() => goToday()} />;
  }
  return null;
}

const styles = StyleSheet.create({
  cardTitle: { fontWeight: '700', color: colors.ink, fontSize: 15 },
  photo: { width: 120, height: 90, borderRadius: radius.sm, backgroundColor: colors.background },
  liveDot: { width: 10, height: 10, borderRadius: 5, backgroundColor: '#17A34A' },
});

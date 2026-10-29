/**
 * Live request screen. Polls the API and renders whichever stage the request is in:
 * proposed → (waitlisted) → offered → dispatched/en route/on site → quoted → in progress → done.
 */
import { router, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { Linking, Pressable, StyleSheet, Text, View } from 'react-native';
import Svg, { Circle, Path } from 'react-native-svg';

import { Icon } from '@/components/icons';
import type { IconName } from '@/components/icons';
import { Avatar, RouteMap, Ring } from '@/components/illustrations';
import { colors } from '@/components/theme';
import { Badge, Body, Button, Card, Checkbox, ErrorText, KeyValue, Loading, Muted, Row, Screen, StepHeader, TextLink, Title } from '@/components/ui';
import { api } from '@/lib/api';
import { POLL_INTERVAL_MS } from '@/lib/config';
import { clockTime, countdown, miles, minutesLabel, money } from '@/lib/format';
import { labelFor, useAction, useCountdown, useOptions, usePolling } from '@/lib/hooks';
import type { ServiceRequest } from '@/lib/types';
import { decorative } from '@/components/a11y';

const LIVE = new Set(['proposed', 'waitlisted', 'offered', 'dispatched', 'en_route', 'on_site',
  'quoted', 'in_progress']);

export default function RequestStatusScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const [request, setRequest] = useState<ServiceRequest | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setRequest(await api.getRequest(id));
      setLoadError(null);
    } catch {
      setLoadError("Couldn't refresh. Retrying…");
    }
  }, [id]);

  useEffect(() => {
    void refresh();
  }, [refresh]);
  usePolling(refresh, POLL_INTERVAL_MS, !!request && LIVE.has(request.status));

  if (!request) return <Loading label={loadError ?? undefined} />;
  const props = { request, onChange: setRequest };
  const view = (() => {
    switch (request.status) {
      case 'proposed': return <Proposed {...props} />;
      case 'waitlisted': return <Waitlisted {...props} />;
      case 'offered': return <Offered {...props} />;
      case 'dispatched':
      case 'en_route':
      case 'on_site': return <Tracking {...props} />;
      case 'quoted': return <Quote {...props} />;
      case 'in_progress': return <InProgress {...props} />;
      case 'completed': return <Completed {...props} />;
      case 'canceled': return <Canceled {...props} />;
      case 'analyzed': return <Expired {...props} />;
      default: return <Loading />;
    }
  })();
  return (
    <>
      {view}
      {loadError ? <Text style={styles.offline}>{loadError}</Text> : null}
    </>
  );
}

type Props = { request: ServiceRequest; onChange: (r: ServiceRequest) => void };

function TechCard({ request, showEta = true }: { request: ServiceRequest; showEta?: boolean }) {
  const options = useOptions();
  const t = request.technician;
  if (!t) return null;
  return (
    <Card style={{ padding: 0, overflow: 'hidden', gap: 0 }}>
      <RouteMap height={110} progress={0} label={`${t.name} is ${miles(t.distance_km)} away`} />
      <View style={{ padding: 14, gap: 10 }}>
        <Row style={{ gap: 12 }}>
          <View style={styles.avatarRing}><Avatar size={56} name={t.name} /></View>
          <View style={{ flex: 1 }}>
            <Text style={styles.techName}>{t.name}</Text>
            <Muted>
              {t.shop_name}
              {t.rating ? ` · ★ ${t.rating.toFixed(1)}` : ''}
            </Muted>
          </View>
          {showEta && t.eta_minutes != null ? (
            <View style={{ alignItems: 'center' }}>
              <Text style={styles.eta}>~{t.eta_minutes}</Text>
              <Muted style={{ fontSize: 11 }}>min</Muted>
            </View>
          ) : null}
        </Row>
        <Row style={{ flexWrap: 'wrap', gap: 6 }}>
          {t.certifications.map((c) => (
            <Chip key={c} icon="shield" label={labelFor(options, 'certifications', c)} />
          ))}
          {t.soft_skills_matched.map((s) => (
            <Chip key={s} icon="check" label={labelFor(options, 'soft_skills', s)} tone="primary" />
          ))}
        </Row>
      </View>
    </Card>
  );
}

function Chip({ icon, label, tone = 'plain' }: { icon: IconName; label: string; tone?: 'plain' | 'primary' }) {
  const primary = tone === 'primary';
  return (
    <View style={[styles.chip, primary && { backgroundColor: colors.primarySoft, borderColor: colors.primarySoft }]}>
      <Icon name={icon} size={12} color={primary ? colors.primary : colors.ink} strokeWidth={2.5} />
      <Text style={[styles.chipText, primary && { color: colors.primary }]}>{label}</Text>
    </View>
  );
}

function Proposed({ request, onChange }: Props) {
  const seconds = useCountdown(request.proposal_expires_at);
  const confirm = useAction(async () => onChange(await api.confirm(request.id)));
  const cancel = useAction(async () => onChange(await api.cancel(request.id)));
  const needsCard = confirm.error?.toLowerCase().includes('payment method');
  return (
    <Screen footer={
      <>
        <Button label={`Confirm booking · hold ${money(request.estimate.low_cents)}`} busy={confirm.busy}
          onPress={() => confirm.run()} />
        <TextLink label="Cancel" color={colors.muted} onPress={() => cancel.run()} />
      </>
    }>
      <StepHeader onBack={() => router.replace('/home')} />
      <Row>
        <View style={styles.checkCircle}><Icon name="check" size={16} color="#FFF" strokeWidth={3} /></View>
        <Title>You're matched</Title>
      </Row>
      <TechCard request={request} />
      <Card tone="muted">
        <KeyValue k="Estimate" v={`from ${money(request.estimate.low_cents)}`} />
        <Muted>A hold is placed on your card now. You're only charged after you approve the
          final price.</Muted>
      </Card>
      {seconds != null ? (
        <Muted style={{ textAlign: 'center' }}>{seconds > 0
          ? `${request.technician?.first_name} is held for you for ${countdown(seconds)}`
          : 'Reservation expired'}</Muted>
      ) : null}
      <ErrorText message={confirm.error ?? cancel.error} />
      {needsCard ? (
        <Button label="Add payment method" variant="secondary" icon="card"
          onPress={() => router.push({ pathname: '/payment', params: { returnTo: `/request/${request.id}` } })} />
      ) : null}
    </Screen>
  );
}

function Waitlisted({ request, onChange }: Props) {
  const [notify, setNotify] = useState(true);
  const widen = useAction(async () => onChange(await api.widen(request.id)));
  const cancel = useAction(async () => onChange(await api.cancel(request.id)));
  const wl = request.waitlist;
  const eta = wl?.eta_minutes;
  const position = wl?.position ?? 1;
  const ahead = Math.max(0, position - 1);
  return (
    <Screen footer={<Button label="Leave waitlist" variant="secondary" busy={cancel.busy}
      onPress={() => cancel.run()} />}>
      <StepHeader onBack={() => router.replace('/home')} />
      <Row style={{ justifyContent: 'space-between' }}>
        <Title>On the waitlist</Title>
        <Badge label="● LIVE" tone="amber" />
      </Row>
      <View style={{ alignItems: 'center' }}>
        <Ring fraction={eta ? Math.max(0.08, 1 - eta / 120) : 0.08}
          big={eta ? `~${eta}` : '…'} small={eta ? 'min to a tech' : 'checking techs'} />
      </View>
      <Card tone="muted" style={styles.queue}>
        <View style={{ alignItems: 'center', gap: 4 }}>
          <View style={styles.queueTech}><Icon name="wrench" size={14} color="#FFF" /></View>
          <Muted style={{ fontSize: 10 }}>Next tech</Muted>
        </View>
        <Icon name="chevronLeft" size={16} color={colors.faint} />
        {Array.from({ length: Math.min(ahead, 4) }, (_, i) => <Person key={i} color={colors.lineStrong} />)}
        <View style={{ alignItems: 'center', gap: 4 }}>
          <Person color={colors.amber} size={30} />
          <Text style={{ fontSize: 10, fontWeight: '700', color: colors.amberInk }}>You · #{position}</Text>
        </View>
      </Card>
      <Body style={{ textAlign: 'center', color: colors.body }}>
        No qualified tech is free nearby yet. We'll match you the moment one is
        {eta ? `, around ${clockTime(eta)}` : ''}.
      </Body>
      <Checkbox label="Text me when I'm matched" checked={notify} onChange={setNotify} />
      {request.soft_skills.length ? (
        <Button label="Ignore my soft-skill picks to go faster" variant="secondary"
          busy={widen.busy} onPress={() => widen.run()} />
      ) : null}
      <ErrorText message={widen.error ?? cancel.error} />
    </Screen>
  );
}

function Person({ color, size = 24 }: { color: string; size?: number }) {
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24" {...decorative}>
      <Circle cx={12} cy={8} r={4} fill={color} />
      <Path d="M4 22c1-7 15-7 16 0z" fill={color} />
    </Svg>
  );
}

function Offered({ request, onChange }: Props) {
  const seconds = useCountdown(request.offer_expires_at);
  const cancel = useAction(async () => onChange(await api.cancel(request.id)));
  return (
    <Screen footer={<TextLink label="Cancel request" color={colors.muted} onPress={() => cancel.run()} />}>
      <StepHeader onBack={() => router.replace('/home')} />
      <Title sub="Your card hold is in place. The shop is confirming the job.">Booking sent</Title>
      <TechCard request={request} />
      <Card tone="soft" style={{ flexDirection: 'row', alignItems: 'center' }}>
        <Icon name="clock" size={20} color={colors.primary} />
        <Body style={{ flex: 1 }}>
          Waiting for {request.technician?.shop_name} to accept
          {seconds ? ` · ${countdown(seconds)}` : ''}
        </Body>
      </Card>
      <Muted>If they don't respond in time, we'll automatically send it to the next best tech.</Muted>
      <ErrorText message={cancel.error} />
    </Screen>
  );
}

const STAGES: { key: string; label: string; icon: IconName }[] = [
  { key: 'dispatched', label: 'Booked', icon: 'check' },
  { key: 'en_route', label: 'En route', icon: 'truck' },
  { key: 'on_site', label: 'Repair', icon: 'wrench' },
  { key: 'completed', label: 'Done', icon: 'star' },
];

function Stages({ status }: { status: string }) {
  const order = ['dispatched', 'en_route', 'on_site', 'quoted', 'in_progress', 'completed'];
  const current = order.indexOf(status);
  const stageIndex = (key: string) => order.indexOf(key);
  return (
    <Row style={{ alignItems: 'flex-start' }}>
      {STAGES.map((s, i) => {
        const done = stageIndex(s.key) < current || status === 'completed';
        const active = !done && (stageIndex(s.key) <= current);
        return (
          <View key={s.key} style={{ flex: 1, alignItems: 'center' }}>
            <Row style={{ alignSelf: 'stretch', gap: 0 }}>
              <View style={[styles.stageLine, { opacity: i === 0 ? 0 : 1, backgroundColor: done || active ? colors.primary : colors.line }]} />
              <View style={[styles.stageDot, done && styles.stageDone, active && styles.stageActive]}>
                <Icon name={done ? 'check' : s.icon} size={13} strokeWidth={2.5}
                  color={done ? '#FFF' : active ? colors.primary : colors.faint} />
              </View>
              <View style={[styles.stageLine, { opacity: i === STAGES.length - 1 ? 0 : 1, backgroundColor: done ? colors.primary : colors.line }]} />
            </Row>
            <Text style={[styles.stageLabel, (done || active) && { color: colors.ink, fontWeight: '600' }]}>{s.label}</Text>
          </View>
        );
      })}
    </Row>
  );
}

function Tracking({ request, onChange }: Props) {
  const t = request.technician;
  const cancel = useAction(async () => onChange(await api.cancel(request.id)));
  const progress = { dispatched: 0.08, en_route: 0.5, on_site: 1 }[request.status as 'dispatched'] ?? 0;
  const headline = { dispatched: 'Booking confirmed', en_route: 'On the way', on_site: 'Your tech has arrived' }[request.status as 'dispatched'];
  return (
    <Screen footer={
      <Row style={{ gap: 8 }}>
        <Button label="Message" variant="secondary" icon="chat" style={{ flex: 1 }}
          onPress={() => t?.shop_phone && Linking.openURL(`sms:${t.shop_phone}`)} />
        <Button label="Call" variant="secondary" icon="phone" style={{ flex: 1 }}
          onPress={() => t?.shop_phone && Linking.openURL(`tel:${t.shop_phone}`)} />
      </Row>
    }>
      <StepHeader onBack={() => router.replace('/home')} />
      <Title>{headline}</Title>
      <Card style={{ padding: 0, overflow: 'hidden' }}>
        <RouteMap height={190} progress={progress} />
      </Card>
      <Row style={{ gap: 12 }}>
        <Avatar size={44} name={t?.name} />
        <View style={{ flex: 1 }}>
          <Body style={{ fontWeight: '700' }}>{t?.name}</Body>
          <Muted>
            {request.status === 'on_site' ? 'Diagnosing your unit'
              : t?.eta_minutes != null ? `Arriving ~${clockTime(t.eta_minutes)}` : t?.shop_name}
          </Muted>
        </View>
      </Row>
      <Stages status={request.status} />
      {request.status !== 'on_site' ? (
        <TextLink label="Cancel booking" color={colors.muted} onPress={() => cancel.run()} />
      ) : null}
      <ErrorText message={cancel.error} />
    </Screen>
  );
}

function Quote({ request, onChange }: Props) {
  const approve = useAction(async () => onChange(await api.approveQuote(request.id)));
  const q = request.quote!;
  const overEstimate = request.estimate.low_cents != null && q.final_price_cents > request.estimate.low_cents;
  return (
    <Screen footer={<Button label={`Approve ${money(q.final_price_cents)}`} busy={approve.busy}
      onPress={() => approve.run()} />}>
      <StepHeader onBack={() => router.replace('/home')} />
      <Title sub={`${request.technician?.name} diagnosed the problem.`}>Approve the final price</Title>
      <Card style={{ alignItems: 'center', paddingVertical: 20 }}>
        <Muted>Final price</Muted>
        <Text style={styles.bigPrice}>{money(q.final_price_cents)}</Text>
        {q.notes ? <Body style={{ textAlign: 'center', color: colors.body }}>{q.notes}</Body> : null}
      </Card>
      <Card tone="muted">
        <KeyValue k="Original estimate" v={`from ${money(request.estimate.low_cents)}`} />
        <KeyValue k="Card on hold" v={money(request.payment.authorized_cents)} />
      </Card>
      {overEstimate ? (
        <Muted>Approving updates your card hold to the final price. You're charged when the job is done.</Muted>
      ) : null}
      <Stages status={request.status} />
      <ErrorText message={approve.error} />
    </Screen>
  );
}

function InProgress({ request }: Props) {
  return (
    <Screen>
      <StepHeader onBack={() => router.replace('/home')} />
      <Title sub="You approved the price. We'll let you know when it's done.">Repair in progress</Title>
      <Card style={{ alignItems: 'center', gap: 10, paddingVertical: 24 }}>
        <View style={styles.wrenchCircle}><Icon name="wrench" size={30} color={colors.primary} /></View>
        <Body>{request.technician?.name} is working on your unit</Body>
        <Muted>Approved: {money(request.quote?.final_price_cents)}</Muted>
      </Card>
      <Stages status={request.status} />
    </Screen>
  );
}

function Completed({ request, onChange }: Props) {
  const rate = useAction(async (stars: number) => onChange(await api.rate(request.id, stars)));
  return (
    <Screen footer={<Button label="Done" onPress={() => router.replace('/home')} />}>
      <View style={{ alignItems: 'center', gap: 8, paddingTop: 12 }}>
        <View style={[styles.checkCircle, { width: 56, height: 56, borderRadius: 28 }]}>
          <Icon name="check" size={28} color="#FFF" strokeWidth={3} />
        </View>
        <Title>Job complete</Title>
      </View>
      <Card>
        <KeyValue k="Technician" v={request.technician?.name ?? '—'} />
        <KeyValue k="Work" v={request.diagnosis?.primary_issue_label ?? 'HVAC service'} />
        <KeyValue k="Charged" v={money(request.payment.captured_cents)} />
        {request.completed_at ? <Muted>{new Date(request.completed_at).toLocaleString()}</Muted> : null}
      </Card>
      <Card tone="soft" style={{ alignItems: 'center' }}>
        <Body style={{ fontWeight: '700' }}>
          {request.rating ? 'Thanks for your rating!' : `How was ${request.technician?.first_name}?`}
        </Body>
        <Row style={{ gap: 6 }}>
          {[1, 2, 3, 4, 5].map((n) => (
            <Pressable key={n} accessibilityRole="button" accessibilityLabel={`${n} star${n > 1 ? 's' : ''}`}
              disabled={!!request.rating || rate.busy} onPress={() => rate.run(n)} hitSlop={6}>
              <Svg width={34} height={34} viewBox="0 0 24 24">
                <Path d="M12 3l2.6 5.6 6.1.7-4.5 4.2 1.2 6L12 16.6 6.6 19.5l1.2-6L3.3 9.3l6.1-.7z"
                  fill={n <= (request.rating ?? 0) ? colors.amber : '#FFFFFF'}
                  stroke={colors.amber} strokeWidth={1.5} strokeLinejoin="round" />
              </Svg>
            </Pressable>
          ))}
        </Row>
      </Card>
      <ErrorText message={rate.error} />
    </Screen>
  );
}

function Canceled({ request }: Props) {
  return (
    <Screen footer={<Button label="Start a new request" onPress={() => router.replace('/request/new')} />}>
      <StepHeader onBack={() => router.replace('/home')} />
      <Title sub={request.canceled_reason ?? undefined}>Request canceled</Title>
      <Muted>Any card hold has been released.</Muted>
    </Screen>
  );
}

function Expired({ request, onChange }: Props) {
  const retry = useAction(async () => onChange(await api.match(request.id)));
  return (
    <Screen footer={<Button label="Find a technician" busy={retry.busy} onPress={() => retry.run()} />}>
      <StepHeader onBack={() => router.replace('/home')} />
      <Title sub="The technician we held for you was released. Let's find you another.">Match expired</Title>
      <ErrorText message={retry.error} />
    </Screen>
  );
}

const styles = StyleSheet.create({
  offline: { position: 'absolute', top: 8, alignSelf: 'center', backgroundColor: colors.ink, color: '#FFF', paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999, fontSize: 12 },
  avatarRing: { marginTop: -34, borderWidth: 3, borderColor: '#FFF', borderRadius: 32 },
  techName: { fontSize: 17, fontWeight: '800', color: colors.ink },
  eta: { fontSize: 18, fontWeight: '800', color: colors.ink },
  chip: { flexDirection: 'row', alignItems: 'center', gap: 4, borderWidth: 1, borderColor: colors.line, borderRadius: 999, paddingHorizontal: 9, paddingVertical: 4 },
  chipText: { fontSize: 11, fontWeight: '600', color: colors.ink },
  checkCircle: { width: 30, height: 30, borderRadius: 15, backgroundColor: colors.primary, alignItems: 'center', justifyContent: 'center' },
  queue: { flexDirection: 'row', alignItems: 'flex-end', justifyContent: 'space-between' },
  queueTech: { width: 28, height: 28, borderRadius: 14, backgroundColor: colors.ink, alignItems: 'center', justifyContent: 'center' },
  stageLine: { flex: 1, height: 2 },
  stageDot: { width: 28, height: 28, borderRadius: 14, borderWidth: 2, borderColor: colors.lineStrong, alignItems: 'center', justifyContent: 'center', backgroundColor: '#FFF' },
  stageDone: { backgroundColor: colors.primary, borderColor: colors.primary },
  stageActive: { borderColor: colors.primary },
  stageLabel: { fontSize: 11, color: colors.muted, marginTop: 4 },
  bigPrice: { fontSize: 44, fontWeight: '800', color: colors.ink, letterSpacing: -1 },
  wrenchCircle: { width: 64, height: 64, borderRadius: 32, backgroundColor: colors.primarySoft, alignItems: 'center', justifyContent: 'center' },
});

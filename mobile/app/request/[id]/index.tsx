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
import { LiveMap } from '@/components/LiveMap';
import { colors } from '@/components/theme';
import { Badge, Body, Button, Card, Checkbox, ErrorText, Field, KeyValue, Loading, Muted, Row, Screen, Segmented, StepHeader, TextLink, Title } from '@/components/ui';
import { api } from '@/lib/api';
import { POLL_INTERVAL_MS } from '@/lib/config';
import { clockTime, countdown, estimateRange, isScheduled, miles, minutesLabel, money, visitTime } from '@/lib/format';
import { labelFor, useAction, useCountdown, useOptions, usePolling } from '@/lib/hooks';
import { copyText, shareSheet, textMessage, whatsApp } from '@/lib/share';
import type { ServiceRequest, ShareInfo } from '@/lib/types';
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
          {showEta && t.arrival_at && isScheduled(t.arrival_at) ? (
            <View style={{ alignItems: 'flex-end', maxWidth: 110 }}>
              <Muted style={{ fontSize: 11 }}>Arrives</Muted>
              <Text style={[styles.eta, { fontSize: 16, textAlign: 'right' }]}>{visitTime(t.arrival_at)}</Text>
            </View>
          ) : showEta && t.eta_minutes != null ? (
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

function usePaymentsOn(): boolean {
  return useOptions()?.features.payments ?? false;
}

function Proposed({ request, onChange }: Props) {
  const payments = usePaymentsOn();
  const seconds = useCountdown(request.proposal_expires_at);
  const confirm = useAction(async () => onChange(await api.confirm(request.id)));
  const cancel = useAction(async () => onChange(await api.cancel(request.id)));
  const needsCard = confirm.error?.toLowerCase().includes('payment method');
  return (
    <Screen footer={
      <>
        <Button label={payments ? `Confirm booking · hold ${money(request.estimate.low_cents)}` : 'Confirm booking'}
          busy={confirm.busy}
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
      {request.technician?.arrival_at && isScheduled(request.technician.arrival_at) ? (
        <Card tone="soft">
          <Body>No one is free right now, so this is the earliest opening:{' '}
            <Text style={{ fontWeight: '700' }}>{visitTime(request.technician.arrival_at)}</Text>.{' '}
            {request.technician.assigned
              ? `It goes on ${request.technician.first_name}'s calendar when you confirm.`
              : 'The time is held for you when you confirm.'}</Body>
        </Card>
      ) : null}
      {request.technician && !request.technician.assigned ? (
        <Muted>{request.technician.shop_name} chooses which of their technicians comes. We'll tell you who as soon as they do.</Muted>
      ) : null}
      <Card tone="muted">
        <KeyValue k="Estimate" v={estimateRange(request.estimate)} />
        <Muted>{payments
          ? "A hold is placed on your card now. You're only charged after you approve the final price."
          : 'You approve the final price before any work. Pay the shop directly when the job is done.'}</Muted>
      </Card>
      {seconds != null ? (
        <Muted style={{ textAlign: 'center' }}>{seconds > 0
          ? `${request.technician?.assigned === false ? 'This time' : request.technician?.first_name} is held for you for ${countdown(seconds)}`
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
  const cancel = useAction(async () => onChange(await api.cancel(request.id)));
  const wl = request.waitlist;
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
      <Body style={{ color: colors.body }}>
        {wl?.reason ?? 'No technician has an opening for this job yet.'}
      </Body>
      <Muted>We check again every few seconds and match you automatically as soon as a
        qualified technician has an opening.</Muted>
      <Checkbox label="Text me when I'm matched" checked={notify} onChange={setNotify} />
      <ErrorText message={cancel.error} />
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
  const payments = usePaymentsOn();
  const seconds = useCountdown(request.offer_expires_at);
  const cancel = useAction(async () => onChange(await api.cancel(request.id)));
  return (
    <Screen footer={<TextLink label="Cancel request" color={colors.muted} onPress={() => cancel.run()} />}>
      <StepHeader onBack={() => router.replace('/home')} />
      <Title sub={payments ? 'Your card hold is in place. The shop is confirming the job.'
        : 'The job is on the technician\'s calendar. The shop is confirming it.'}>Booking sent</Title>
      <TechCard request={request} />
      <Card tone="soft" style={{ flexDirection: 'row', alignItems: 'center' }}>
        <Icon name="clock" size={20} color={colors.primary} />
        <Body style={{ flex: 1 }}>
          Waiting for {request.technician?.shop_name} to accept
          {seconds && seconds < 3600 ? ` · ${countdown(seconds)}`
            : request.offer_expires_at ? ` by ${visitTime(request.offer_expires_at)}` : ''}
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

/** Message the shop (in the app) and call the shop, or the technician if their company allows. */
function ContactBar({ request }: { request: ServiceRequest }) {
  const t = request.technician;
  if (!t) return null;
  const call = (phone: string) => Linking.openURL(`tel:${phone}`);
  return (
    <View style={{ gap: 8 }}>
      {request.chat_open ? (
        <Button label="Message" variant="secondary" icon="chat"
          onPress={() => router.push(`/request/${request.id}/chat`)} />
      ) : null}
      <Row style={{ gap: 8 }}>
        {t.shop_phone ? (
          <Button label="Call shop" variant="secondary" icon="phone" style={{ flex: 1 }}
            accessibilityLabel={`Call ${t.shop_name}`} onPress={() => call(t.shop_phone!)} />
        ) : null}
        {t.phone ? (
          <Button label={`Call ${t.first_name}`} variant="secondary" icon="phone" style={{ flex: 1 }}
            accessibilityLabel={`Call ${t.name}`} onPress={() => call(t.phone!)} />
        ) : null}
      </Row>
    </View>
  );
}

function Tracking({ request, onChange }: Props) {
  const t = request.technician;
  const cancel = useAction(async () => onChange(await api.cancel(request.id)));
  const progress = { dispatched: 0.08, en_route: 0.5, on_site: 1 }[request.status as 'dispatched'] ?? 0;
  const headline = { dispatched: 'Booking confirmed', en_route: 'On the way', on_site: 'Your tech has arrived' }[request.status as 'dispatched'];
  // The live map appears ONLY while the technician is driving to this home.
  const live = request.status === 'en_route' ? t?.location : null;
  return (
    <Screen footer={<ContactBar request={request} />}>
      <StepHeader onBack={() => router.replace('/home')} />
      <Title>{headline}</Title>
      <Card style={{ padding: 0, overflow: 'hidden' }}>
        {live ? (
          <>
            <LiveMap lat={live.lat} lng={live.lng} label={`${t?.first_name ?? 'Technician'}'s location`} />
            <Row style={{ padding: 10, gap: 6 }}>
              <View style={styles.liveDot} />
              <Muted style={{ flex: 1 }}>Live · updated {t?.location_updated_at ? agoLabel(t.location_updated_at) : 'just now'}</Muted>
            </Row>
          </>
        ) : (
          <>
            <RouteMap height={190} progress={progress} />
            {request.status === 'dispatched' ? (
              <Muted style={{ padding: 10 }}>You'll see {t?.first_name ?? 'your technician'} on a live map once they're on the way to you.</Muted>
            ) : request.status === 'en_route' ? (
              <Muted style={{ padding: 10 }}>Waiting for {t?.first_name ?? 'your technician'}'s location…</Muted>
            ) : null}
          </>
        )}
      </Card>
      <Row style={{ gap: 12 }}>
        <Avatar size={44} name={t?.name} />
        <View style={{ flex: 1 }}>
          <Body style={{ fontWeight: '700' }}>{t?.name}</Body>
          <Muted>
            {request.status === 'on_site' ? 'Diagnosing your unit'
              : t?.arrival_at && isScheduled(t.arrival_at) ? `Visit ${visitTime(t.arrival_at)}`
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

function agoLabel(iso: string): string {
  const seconds = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (seconds < 10) return 'just now';
  if (seconds < 60) return `${seconds} s ago`;
  return `${Math.round(seconds / 60)} min ago`;
}

function Quote({ request, onChange }: Props) {
  const payments = usePaymentsOn();
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
        <KeyValue k="Original estimate" v={estimateRange(request.estimate)} />
        {payments ? <KeyValue k="Card on hold" v={money(request.payment.authorized_cents)} /> : null}
      </Card>
      {payments && overEstimate ? (
        <Muted>Approving updates your card hold to the final price. You're charged when the job is done.</Muted>
      ) : null}
      <Stages status={request.status} />
      <ErrorText message={approve.error} />
    </Screen>
  );
}

function InProgress({ request }: Props) {
  return (
    <Screen footer={<ContactBar request={request} />}>
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
  const t = request.technician;
  const [techStars, setTechStars] = useState(request.rating ?? 0);
  const [shopStars, setShopStars] = useState(request.shop_rating ?? 0);
  const [review, setReview] = useState('');
  const rated = request.rating != null || request.shop_rating != null;
  const rate = useAction(async () => onChange(await api.rate(request.id, {
    technician_rating: techStars || undefined,
    shop_rating: shopStars || undefined,
    review: review.trim() || undefined,
  })));
  return (
    <Screen footer={<Button label="Done" variant={rated ? 'primary' : 'secondary'} onPress={() => router.replace('/home')} />}>
      <View style={{ alignItems: 'center', gap: 8, paddingTop: 12 }}>
        <View style={[styles.checkCircle, { width: 56, height: 56, borderRadius: 28 }]}>
          <Icon name="check" size={28} color="#FFF" strokeWidth={3} />
        </View>
        <Title>Job complete</Title>
      </View>
      <Card>
        <KeyValue k="Technician" v={t?.name ?? '—'} />
        <KeyValue k="Company" v={t?.shop_name ?? '—'} />
        <KeyValue k="Work" v={request.diagnosis?.primary_issue_label ?? 'HVAC service'} />
        {request.payment.captured_cents != null
          ? <KeyValue k="Charged" v={money(request.payment.captured_cents)} />
          : <KeyValue k="Price" v={`${money(request.quote?.final_price_cents)} · pay the shop`} />}
        {request.completed_at ? <Muted>{new Date(request.completed_at).toLocaleString()}</Muted> : null}
      </Card>
      <Card tone="soft" style={{ gap: 12 }}>
        <Body style={{ fontWeight: '700' }}>{rated ? 'Thanks for your ratings!' : 'Rate your experience'}</Body>
        <StarRow label={`${t?.first_name ?? 'Technician'} (technician)`} value={techStars}
          locked={request.rating != null} onChange={setTechStars} />
        <StarRow label={`${t?.shop_name ?? 'Company'} (company)`} value={shopStars}
          locked={request.shop_rating != null} onChange={setShopStars} />
        {!rated ? (
          <>
            <Field label="Anything to add? (optional)" value={review} onChangeText={setReview}
              placeholder="On time, explained the fix..." maxLength={500} />
            <Button label="Submit ratings" busy={rate.busy} disabled={!techStars && !shopStars}
              onPress={() => rate.run()} />
          </>
        ) : null}
        <ErrorText message={rate.error} />
      </Card>
      <SharePanel request={request} />
    </Screen>
  );
}

function StarRow({ label, value, locked, onChange }: {
  label: string; value: number; locked: boolean; onChange: (n: number) => void;
}) {
  return (
    <View style={{ gap: 4 }}>
      <Muted>{label}</Muted>
      <Row style={{ gap: 6 }} >
        {[1, 2, 3, 4, 5].map((n) => (
          <Pressable key={n} accessibilityRole="button"
            accessibilityLabel={`${label}: ${n} star${n > 1 ? 's' : ''}`}
            accessibilityState={{ selected: n <= value, disabled: locked }}
            disabled={locked} onPress={() => onChange(n)} hitSlop={6}>
            <Svg width={32} height={32} viewBox="0 0 24 24" {...decorative}>
              <Path d="M12 3l2.6 5.6 6.1.7-4.5 4.2 1.2 6L12 16.6 6.6 19.5l1.2-6L3.3 9.3l6.1-.7z"
                fill={n <= value ? colors.amber : '#FFFFFF'}
                stroke={colors.amber} strokeWidth={1.5} strokeLinejoin="round" />
            </Svg>
          </Pressable>
        ))}
      </Row>
    </View>
  );
}

/** Recommend the technician or company to a group chat or a friend. */
function SharePanel({ request }: { request: ServiceRequest }) {
  const [info, setInfo] = useState<ShareInfo | null>(null);
  const [who, setWho] = useState<'technician' | 'shop'>('technician');
  const [note, setNote] = useState<string | null>(null);
  const load = useAction(async () => setInfo(await api.share(request.id)));
  useEffect(() => { void load.run(); }, [request.id, request.rating, request.shop_rating]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!info) return load.error ? <ErrorText message={load.error} /> : null;
  const target = info[who];
  const act = async (fn: () => Promise<unknown>, done: string) => {
    try {
      const result = await fn();
      setNote(result === 'copied' ? 'Copied. Paste it into your group chat.' : done);
    } catch {
      setNote("Couldn't open that app. Use Copy instead.");
    }
  };
  return (
    <Card style={{ gap: 10 }}>
      <Row>
        <Icon name="chat" size={18} color={colors.primary} />
        <Body style={{ fontWeight: '700', flex: 1 }}>Share with friends or a group chat</Body>
      </Row>
      <Segmented value={who} onChange={(v) => { setWho(v as 'technician' | 'shop'); setNote(null); }}
        options={[
          { value: 'technician', label: request.technician?.first_name ?? 'Technician' },
          { value: 'shop', label: 'Company' },
        ]} />
      <Card tone="muted"><Muted selectable>{target.message}</Muted></Card>
      <Button label="Share…" icon="chat" onPress={() => act(() => shareSheet(target.message, target.title), 'Shared!')} />
      <Row style={{ gap: 8 }}>
        <View style={{ flex: 1 }}>
          <Button label="Text" variant="secondary" onPress={() => act(() => textMessage(target.message), '')} />
        </View>
        <View style={{ flex: 1 }}>
          <Button label="WhatsApp" variant="secondary" onPress={() => act(() => whatsApp(target.message), '')} />
        </View>
        <View style={{ flex: 1 }}>
          <Button label="Copy" variant="secondary"
            onPress={() => act(async () => { await copyText(target.message); return 'copied'; }, '')} />
        </View>
      </Row>
      {note ? <Muted accessibilityLiveRegion="polite">{note}</Muted> : null}
    </Card>
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
  liveDot: { width: 10, height: 10, borderRadius: 5, backgroundColor: '#17A34A' },
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

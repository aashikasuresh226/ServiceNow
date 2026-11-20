/** A job from the company's Housecall Pro, run from this app: On my way, Arrived, Start,
 * line items (work and prices), notes, photos, Finish. Line items, notes and photos go into
 * the Housecall Pro job; each step is added to it as a timestamped note (Housecall Pro's
 * API can't change a job's status), and the office invoices the job there. */
import * as ImagePicker from 'expo-image-picker';
import { router, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { Linking, Platform, Text, View } from 'react-native';

import { Icon } from '@/components/icons';
import { IssuePicker } from '@/components/IssuePicker';
import { colors } from '@/components/theme';
import { Badge, Body, Button, Card, ErrorText, Field, Loading, Muted, Row, Screen, StepHeader, Title } from '@/components/ui';
import { techApi } from '@/lib/api';
import { money, visitTime } from '@/lib/format';
import { useAction, useOptions } from '@/lib/hooks';
import type { OutsideJobDetail, OutsideStep } from '@/lib/types';

function goToday() {
  if (router.canGoBack()) router.dismissTo('/tech');
  else router.replace('/tech');
}

const NEXT: Record<string, { step: OutsideStep; label: string; icon: 'truck' | 'mapPin' | 'wrench' | 'check' }[]> = {
  '': [{ step: 'on_my_way', label: 'On my way', icon: 'truck' }, { step: 'arrived', label: "I've arrived", icon: 'mapPin' }],
  en_route: [{ step: 'arrived', label: "I've arrived", icon: 'mapPin' }],
  on_site: [{ step: 'started', label: 'Start work', icon: 'wrench' }],
  working: [],
  finished: [],
};

const STATUS_TEXT: Record<string, string> = {
  '': 'Not started',
  en_route: 'On the way',
  on_site: 'On site',
  working: 'Working',
  finished: 'Finished in the app',
};

const time = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });

export default function OutsideJobScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const [job, setJob] = useState<OutsideJobDetail | null>(null);
  const [missing, setMissing] = useState(false);
  const [itemName, setItemName] = useState('');
  const [itemQty, setItemQty] = useState('1');
  const [itemPrice, setItemPrice] = useState('');
  const [note, setNote] = useState('');
  const [summary, setSummary] = useState('');
  const [finishing, setFinishing] = useState(false);
  const [issue, setIssue] = useState<string | null>(null);
  const options = useOptions();

  const load = useCallback(() => {
    techApi.outsideJob(id).then(setJob).catch(() => setMissing(true));
  }, [id]);
  useEffect(load, [load]);

  const step = useAction(async (next: OutsideStep) => {
    setJob(await techApi.outsideStep(
      id, next, next === 'finished' ? summary : undefined, next === 'finished' ? issue ?? undefined : undefined,
    ));
    if (next === 'finished') setFinishing(false);
  });
  const addItem = useAction(async () => {
    const cents = Math.round(parseFloat(itemPrice.replace(/[$,\s]/g, '')) * 100);
    const quantity = parseFloat(itemQty) || 1;
    if (!Number.isFinite(cents) || cents < 0) throw new Error('Enter a price, like 185 or 185.50');
    setJob(await techApi.outsideLineItem(id, itemName.trim(), quantity, cents));
    setItemName(''); setItemQty('1'); setItemPrice('');
  });
  const addNote = useAction(async () => {
    setJob(await techApi.outsideNote(id, note));
    setNote('');
  });
  const addPhoto = useAction(async (source: 'camera' | 'library') => {
    const options: ImagePicker.ImagePickerOptions = { mediaTypes: ['images'], quality: 0.7 };
    if (source === 'camera' && Platform.OS !== 'web') {
      const permission = await ImagePicker.requestCameraPermissionsAsync();
      if (!permission.granted) throw new Error('Camera permission is needed to take a photo');
    }
    const result = source === 'camera' && Platform.OS !== 'web'
      ? await ImagePicker.launchCameraAsync(options)
      : await ImagePicker.launchImageLibraryAsync(options);
    const asset = result.canceled ? undefined : result.assets[0];
    if (asset) setJob(await techApi.outsidePhoto(id, asset.uri, asset.mimeType ?? 'image/jpeg'));
  });
  const retry = useAction(async () => setJob(await techApi.outsideRetry(id)));

  if (missing) {
    return (
      <Screen footer={<Button label="Back to today" onPress={goToday} />}>
        <StepHeader onBack={goToday} />
        <Card tone="muted"><Muted>This job is no longer assigned to you.</Muted></Card>
      </Screen>
    );
  }
  if (!job) return <Loading />;

  const directions = job.address
    ? (Platform.OS === 'ios' ? 'http://maps.apple.com/?daddr=' : 'https://www.google.com/maps/dir/?api=1&destination=')
      + encodeURIComponent(job.address)
    : null;
  const working = job.app_status === 'working' || job.app_status === 'on_site';
  const finished = job.app_status === 'finished';
  const itemsTotal = job.line_items?.reduce((sum, i) => sum + i.total_cents, 0) ?? 0;
  const error = step.error ?? addItem.error ?? addNote.error ?? addPhoto.error ?? retry.error;

  return (
    <Screen footer={
      finished ? <Button label="Back to today" onPress={goToday} />
        : finishing ? (
          <Button label="Finish job" icon="check" busy={step.busy} disabled={!issue || !summary.trim()}
            onPress={() => step.run('finished')} />
        ) : working ? (
          <View style={{ gap: 8 }}>
            {(NEXT[job.app_status] ?? []).map((n) => (
              <Button key={n.step} label={n.label} icon={n.icon} busy={step.busy} onPress={() => step.run(n.step)} />
            ))}
            <Button label="Finish job" variant={job.app_status === 'working' ? 'primary' : 'secondary'} icon="check"
              onPress={() => setFinishing(true)} />
          </View>
        ) : (
          <View style={{ gap: 8 }}>
            {(NEXT[job.app_status] ?? []).map((n, i) => (
              <Button key={n.step} label={n.label} icon={n.icon} variant={i === 0 ? 'primary' : 'secondary'}
                busy={step.busy} onPress={() => step.run(n.step)} />
            ))}
          </View>
        )
    }>
      <StepHeader onBack={goToday} />
      <Row style={{ justifyContent: 'space-between' }}>
        <Badge label="Housecall Pro" tone="neutral" />
        <Badge label={STATUS_TEXT[job.app_status] ?? job.app_status} tone={finished ? 'success' : job.app_status ? 'amber' : 'neutral'} />
      </Row>
      <Title sub={job.starts_at ? visitTime(job.starts_at) : 'Not scheduled yet'}>{job.customer_name ?? 'Customer'}</Title>
      {job.address ? <Muted>{job.address}</Muted> : null}
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
        <Text style={styles.label}>Job</Text>
        <Body>{job.description ?? 'No description'}</Body>
        {job.invoice_number ? <Muted>Job #{job.invoice_number}</Muted> : null}
      </Card>

      {finishing && !finished ? (
        <Card tone="soft" style={{ gap: 8 }}>
          <Body style={{ fontWeight: '700' }}>Finish the job</Body>
          <IssuePicker options={options?.issues ?? []} value={issue} onChange={setIssue} />
          <Field label="What did you do? (added to the job in Housecall Pro)" value={summary} onChangeText={setSummary}
            multiline maxLength={2000} placeholder="Replaced the run capacitor, tested cooling…" />
          <Muted>{job.line_items ? `Line items total ${money(itemsTotal)}. ` : ''}The office sends the invoice from Housecall Pro.</Muted>
          <Button label="Not yet" variant="secondary" onPress={() => setFinishing(false)} />
        </Card>
      ) : null}

      <Card style={{ gap: 8 }}>
        <Row style={{ justifyContent: 'space-between' }}>
          <Text style={styles.label}>Line items</Text>
          {job.line_items?.length ? <Body style={{ fontWeight: '700' }}>{money(itemsTotal)}</Body> : null}
        </Row>
        {job.line_items === null ? <Muted>Couldn't load the job's line items from Housecall Pro right now.</Muted>
          : job.line_items.length ? job.line_items.map((item, i) => (
            <Row key={`${item.name}${i}`} style={{ justifyContent: 'space-between' }}>
              <Body style={{ flex: 1 }}>{item.quantity !== 1 ? `${item.quantity} × ` : ''}{item.name}</Body>
              <Body>{money(item.total_cents)}</Body>
            </Row>
          )) : <Muted>No line items yet.</Muted>}
        {!finished ? (
          <View style={{ gap: 8, marginTop: 4 }}>
            <Field label="Work or part" value={itemName} onChangeText={setItemName} maxLength={120}
              placeholder="Run capacitor 45/5 µF" />
            <Row style={{ gap: 8 }}>
              <View style={{ width: 90 }}>
                <Field label="Qty" value={itemQty} onChangeText={setItemQty} keyboardType="decimal-pad" />
              </View>
              <View style={{ flex: 1 }}>
                <Field label="Price each ($)" value={itemPrice} onChangeText={setItemPrice} keyboardType="decimal-pad" placeholder="185.00" />
              </View>
            </Row>
            <Button label="Add line item" variant="secondary" icon="plus" busy={addItem.busy}
              disabled={!itemName.trim() || !itemPrice.trim()} onPress={() => addItem.run()} />
          </View>
        ) : null}
      </Card>

      {!finished ? (
        <Card style={{ gap: 8 }}>
          <Text style={styles.label}>Notes and photos</Text>
          <Field label="Note for the office" value={note} onChangeText={setNote} multiline maxLength={2000}
            placeholder="Contactor is pitted; recommend replacing next visit" />
          <Row style={{ gap: 8 }}>
            <Button label="Add note" variant="secondary" style={{ flex: 1 }} busy={addNote.busy} disabled={!note.trim()}
              onPress={() => addNote.run()} />
            <Button label={Platform.OS === 'web' ? 'Add photo' : 'Take photo'} variant="secondary" icon="camera" style={{ flex: 1 }}
              busy={addPhoto.busy} onPress={() => addPhoto.run('camera')} />
          </Row>
        </Card>
      ) : null}

      <ErrorText message={error} />

      {job.activity.length ? (
        <View style={{ gap: 6 }}>
          <Row style={{ justifyContent: 'space-between' }}>
            <Text style={styles.label}>Sent to Housecall Pro</Text>
            {job.unsent ? <Button label="Retry now" variant="secondary" busy={retry.busy} onPress={() => retry.run()} /> : null}
          </Row>
          {job.activity.map((a) => (
            <Row key={a.id} style={{ alignItems: 'flex-start' }}>
              <Icon name={a.sent ? 'check' : 'clock'} size={16} color={a.sent ? colors.success : colors.amberInk} />
              <View style={{ flex: 1 }}>
                <Body>{a.text}</Body>
                <Muted>{time(a.created_at)}{a.sent ? '' : ` · waiting to send${a.error ? ` (${a.error})` : ''}`}</Muted>
              </View>
            </Row>
          ))}
        </View>
      ) : null}

      <Row style={{ alignItems: 'flex-start' }}>
        <Icon name="info" size={18} color={colors.muted} />
        <Muted style={{ flex: 1 }}>
          Line items, notes and photos go straight into this job in Housecall Pro. Each step (on my way, arrived,
          started, finished) is added there as a note with the time, and the office sends the invoice from Housecall Pro.
          {job.customer_uses_app ? ' This customer uses the app and gets a text when you tap On my way.' : ''}
        </Muted>
      </Row>
    </Screen>
  );
}

const styles = {
  label: { fontSize: 12, fontWeight: '700' as const, color: colors.muted, textTransform: 'uppercase' as const },
};

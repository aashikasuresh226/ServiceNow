import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { Image, StyleSheet, Text, View } from 'react-native';
import Svg, { Path, Rect } from 'react-native-svg';

import { Icon } from '@/components/icons';
import type { IconName } from '@/components/icons';
import { AcUnit } from '@/components/illustrations';
import { colors } from '@/components/theme';
import { Badge, Body, Button, Card, ErrorText, Field, Loading, Muted, Row, Screen, Segmented, StepHeader, TextLink, Title } from '@/components/ui';
import { api } from '@/lib/api';
import { labelFor, useAction, useOptions } from '@/lib/hooks';
import type { ServiceRequest, UnitInfo } from '@/lib/types';
import { decorative } from '@/components/a11y';

const CONFIDENCE_BARS = { low: 1, medium: 2, high: 3 } as const;

export default function DiagnosisScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const options = useOptions();
  const [request, setRequest] = useState<ServiceRequest | null>(null);
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    api.getRequest(id).then(setRequest).catch(() => undefined);
  }, [id]);

  if (!request || !options) return <Loading />;
  const unit = request.unit;
  const dx = request.diagnosis;
  if (!unit || !dx) return <Loading label="Waiting for analysis…" />;
  const bars = CONFIDENCE_BARS[dx.confidence];

  // Nothing the AI could use: say so plainly, no guessed problem or price.
  if (dx.analysis === 'skipped' || dx.analysis === 'photo_unusable') {
    const skipped = dx.analysis === 'skipped';
    return (
      <Screen footer={
        <>
          <Button label={skipped ? 'Add a photo' : 'Retake the photo'} icon="camera"
            onPress={() => router.replace(`/request/${id}/photo`)} />
          <TextLink label="Continue without an AI check" color={colors.muted}
            onPress={() => router.push(`/request/${id}/estimate`)} />
        </>
      }>
        <StepHeader step={3} />
        <Title sub={skipped
          ? "You didn't add a photo or describe the problem, so there's nothing for the AI to check and no estimate."
          : "The AI couldn't read your photo, so it hasn't guessed the problem or a price."}>
          {skipped ? 'Nothing to check yet' : 'We need a clearer photo'}
        </Title>
        {unit.photo_feedback ? (
          <Card tone="amber" style={{ flexDirection: 'row', alignItems: 'flex-start' }}>
            <Icon name="camera" size={18} color={colors.amberInk} />
            <Body style={{ flex: 1, color: colors.amberInk }}>{unit.photo_feedback}</Body>
          </Card>
        ) : null}
        <Card tone="muted" style={{ gap: 6 }}>
          <Body style={{ fontWeight: '700' }}>For an AI check and a price estimate</Body>
          <Muted>• A photo of the outdoor unit with its label (the silver sticker) visible</Muted>
          <Muted>• Or a few words about what's happening, e.g. "fan outside isn't spinning, humming noise"</Muted>
        </Card>
        <Muted>Or continue: your technician diagnoses the problem and gives you the price before any work starts.</Muted>
      </Screen>
    );
  }
  const identified = dx.primary_issue !== 'general_diagnostic';

  return (
    <Screen footer={<Button label="See estimate" onPress={() => router.push(`/request/${id}/estimate`)} />}>
      <StepHeader step={3} />
      <Title>Here's what we found</Title>

      {dx.safety_warning ? (
        <Card tone="amber" style={{ flexDirection: 'row', alignItems: 'flex-start' }}>
          <Icon name="alert" size={20} color={colors.amberInk} />
          <Body style={{ flex: 1, color: colors.amberInk, fontWeight: '600' }}>{dx.safety_warning}</Body>
        </Card>
      ) : null}

      <Card style={{ padding: 10 }}>
        <View style={styles.unitHero}>
          {request.photos[0] ? (
            <Image source={{ uri: request.photos[0].url }} style={styles.photo} accessibilityLabel="Your unit" />
          ) : (
            <AcUnit width={110} highlightLabel />
          )}
          <View style={styles.identified}>
            <Icon name="sparkle" size={11} color={colors.primary} strokeWidth={3} />
            <Text style={styles.identifiedText}>
              {unit.edited_by_homeowner ? 'Edited by you' : dx.ai_used === false ? 'Your photo' : 'Identified'}
            </Text>
          </View>
        </View>
        {dx.ai_used === false && !unit.edited_by_homeowner ? null : (
        <Row style={{ justifyContent: 'space-around' }}>
          <Fact icon="building" value={unit.brand ?? 'Unknown'} />
          <Fact icon="tag" value={unit.model_number ?? '—'} />
          <Fact icon="calendar" value={ageLabel(unit)} />
        </Row>
        )}
        {dx.ai_used === false && !unit.edited_by_homeowner ? null : (
          <Muted style={{ textAlign: 'center' }}>{labelFor(options, 'equipment_types', unit.equipment_type)}</Muted>
        )}
        {labelFacts(unit).length ? (
          <Row style={{ flexWrap: 'wrap', justifyContent: 'center', gap: 6 }}>
            {labelFacts(unit).map((f) => <Badge key={f} label={f} tone="neutral" />)}
          </Row>
        ) : null}
      </Card>
      {unit.photo_feedback ? (
        <Card tone="amber" style={{ flexDirection: 'row', alignItems: 'flex-start' }}>
          <Icon name="camera" size={18} color={colors.amberInk} />
          <Body style={{ flex: 1, color: colors.amberInk }}>{unit.photo_feedback}</Body>
        </Card>
      ) : null}
      {dx.ai_error ? (
        <Card tone="amber" style={{ gap: 4 }}>
          <Body style={{ color: colors.amberInk, fontWeight: '700' }}>Photo analysis didn't work this time</Body>
          <Body style={{ color: colors.amberInk }}>Reason: {dx.ai_error}.</Body>
          <Muted>You can still book: your photos and description go to the technician, who
            diagnoses it on site.</Muted>
        </Card>
      ) : dx.ai_used === false ? (
        <Card tone="muted">
          <Muted>Photo analysis isn't switched on yet, so we haven't guessed the problem. Your
            photos and description go to the technician, who diagnoses it on site.</Muted>
        </Card>
      ) : !identified ? (
        <Card tone="muted">
          <Muted>The AI couldn't tell the problem from this, so it hasn't guessed one or a price.
            Your technician diagnoses it on site.</Muted>
        </Card>
      ) : null}

      {dx.ai_used === false || !identified ? null : (
      <Card tone="soft" style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
        <Svg width={40} height={44} viewBox="0 0 40 44" {...decorative}>
          <Path d="M15 8V2M25 8V2" stroke={colors.primary} strokeWidth={2.5} strokeLinecap="round" />
          <Rect x={8} y={8} width={24} height={32} rx={5} fill="#FFFFFF" stroke={colors.primary} strokeWidth={2.5} />
          <Path d="M22 16l-5 8h6l-3 8" fill="none" stroke={colors.amber} strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" />
        </Svg>
        <View style={{ flex: 1, gap: 4 }}>
          <Text style={styles.small}>Likely issue</Text>
          <Text style={styles.issue}>{dx.primary_issue_label}</Text>
          <Row style={{ gap: 3 }} >
            {[1, 2, 3].map((n) => (
              <View key={n} style={[styles.bar, { backgroundColor: n <= bars ? colors.primary : '#B7C6F2' }]} />
            ))}
            <Muted style={{ marginLeft: 4, fontSize: 11 }}>{dx.confidence} confidence</Muted>
          </Row>
        </View>
      </Card>
      )}
      {dx.ai_used === false || !identified ? null : <Body style={{ color: colors.body }}>{dx.summary}</Body>}
      {dx.visible_issues?.length ? (
        <View style={{ gap: 4 }}>
          <Muted>Seen in your photo:</Muted>
          {dx.visible_issues.map((v) => <Body key={v} style={{ color: colors.body }}>• {v}</Body>)}
        </View>
      ) : null}
      {dx.alternatives.length ? (
        <Row style={{ flexWrap: 'wrap' }}>
          <Muted>Also possible:</Muted>
          {dx.alternatives.map((a) => <Badge key={a.issue} label={a.label} tone="neutral" />)}
        </Row>
      ) : null}
      <Row style={{ justifyContent: 'space-between' }}>
        <Muted>{dx.ai_used === false ? 'Diagnosed on site' : 'Read by AI · your technician confirms'}</Muted>
        {!editing ? <TextLink label="Edit details" onPress={() => setEditing(true)} /> : null}
      </Row>
      {editing ? <EditUnit request={request} onSaved={(r) => { setRequest(r); setEditing(false); }} /> : null}
    </Screen>
  );
}

function ageLabel(unit: UnitInfo): string {
  if (unit.manufacture_year) return `${unit.manufacture_year} (~${unit.approx_age_years ?? '?'} yrs)`;
  return unit.approx_age_years != null ? `~${unit.approx_age_years} yrs` : 'Age ?';
}

function labelFacts(unit: UnitInfo): string[] {
  const facts: string[] = [];
  if (unit.tonnage) facts.push(`${unit.tonnage} ton`);
  if (unit.refrigerant) facts.push(unit.refrigerant);
  if (unit.seer_rating) facts.push(`SEER ${unit.seer_rating}`);
  if (unit.fuel) facts.push(unit.fuel.replace('_', ' '));
  if (unit.voltage) facts.push(unit.voltage);
  if (unit.serial_number) facts.push(`S/N ${unit.serial_number}`);
  return facts;
}

function Fact({ icon, value }: { icon: IconName; value: string }) {
  return (
    <View style={{ alignItems: 'center', gap: 4, flex: 1 }}>
      <Icon name={icon} size={18} color={colors.primary} />
      <Text style={{ fontWeight: '700', fontSize: 12, color: colors.ink }} numberOfLines={1}>{value}</Text>
    </View>
  );
}

function EditUnit({ request, onSaved }: { request: ServiceRequest; onSaved: (r: ServiceRequest) => void }) {
  const options = useOptions();
  const unit = request.unit!;
  const [brand, setBrand] = useState(unit.brand ?? '');
  const [model, setModel] = useState(unit.model_number ?? '');
  const [age, setAge] = useState(unit.approx_age_years?.toString() ?? '');
  const [type, setType] = useState(unit.equipment_type);
  const save = useAction(async () => {
    onSaved(await api.updateUnit(request.id, {
      brand, model_number: model, equipment_type: type,
      ...(age ? { approx_age_years: Number(age) } : {}),
    }));
  });
  const types = (options?.equipment_types ?? []).filter((t) =>
    ['central_ac', 'heat_pump', 'furnace', 'unknown'].includes(t.value));
  return (
    <Card style={{ gap: 12 }}>
      <Segmented options={types} value={type} onChange={setType} />
      <Field label="Brand" value={brand} onChangeText={setBrand} />
      <Field label="Model number" value={model} onChangeText={setModel} autoCapitalize="characters" />
      <Field label="Age (years)" value={age} onChangeText={(v) => setAge(v.replace(/\D/g, ''))} keyboardType="number-pad" />
      <ErrorText message={save.error} />
      <Button label="Save" variant="secondary" busy={save.busy} onPress={() => save.run()} />
    </Card>
  );
}

const styles = StyleSheet.create({
  unitHero: {
    height: 120, borderRadius: 10, backgroundColor: '#EEF0F4', alignItems: 'center',
    justifyContent: 'center', overflow: 'hidden',
  },
  photo: { width: '100%', height: '100%' },
  identified: {
    position: 'absolute', left: 8, top: 8, flexDirection: 'row', alignItems: 'center', gap: 4,
    backgroundColor: '#FFFFFF', borderRadius: 999, paddingHorizontal: 8, paddingVertical: 2,
  },
  identifiedText: { fontSize: 10, fontWeight: '700', color: colors.primary },
  small: { fontSize: 11, fontWeight: '700', color: colors.primary },
  issue: { fontSize: 16, fontWeight: '800', color: colors.ink },
  bar: { width: 18, height: 5, borderRadius: 3 },
});

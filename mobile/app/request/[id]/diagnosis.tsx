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
import type { ServiceRequest } from '@/lib/types';
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
            <Text style={styles.identifiedText}>{unit.edited_by_homeowner ? 'Edited by you' : 'Identified'}</Text>
          </View>
        </View>
        <Row style={{ justifyContent: 'space-around' }}>
          <Fact icon="building" value={unit.brand ?? 'Unknown'} />
          <Fact icon="tag" value={unit.model_number ?? '—'} />
          <Fact icon="calendar" value={unit.approx_age_years != null ? `~${unit.approx_age_years} yrs` : 'Age ?'} />
        </Row>
        <Muted style={{ textAlign: 'center' }}>{labelFor(options, 'equipment_types', unit.equipment_type)}</Muted>
      </Card>

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
      <Body style={{ color: colors.body }}>{dx.summary}</Body>
      {dx.alternatives.length ? (
        <Row style={{ flexWrap: 'wrap' }}>
          <Muted>Also possible:</Muted>
          {dx.alternatives.map((a) => <Badge key={a.issue} label={a.label} tone="neutral" />)}
        </Row>
      ) : null}
      <Row style={{ justifyContent: 'space-between' }}>
        <Muted>AI suggestion · your technician confirms</Muted>
        {!editing ? <TextLink label="Edit details" onPress={() => setEditing(true)} /> : null}
      </Row>
      {editing ? <EditUnit request={request} onSaved={(r) => { setRequest(r); setEditing(false); }} /> : null}
    </Screen>
  );
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
    height: 120, borderRadius: 10, backgroundColor: '#EEF0F3', alignItems: 'center',
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

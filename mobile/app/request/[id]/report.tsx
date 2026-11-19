/** Report a problem with the technician. It goes to their company and to the HVAC Connect
 * team; the technician doesn't see it. One report per job; the company's reply shows here. */
import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { Pressable, Text, View } from 'react-native';

import { Icon } from '@/components/icons';
import { colors } from '@/components/theme';
import { Badge, Body, Button, Card, ErrorText, Field, Loading, Muted, Row, Screen, StepHeader, Title } from '@/components/ui';
import { api } from '@/lib/api';
import { APP_NAME } from '@/lib/config';
import { useAction } from '@/lib/hooks';
import type { ComplaintState, ServiceRequest } from '@/lib/types';

export default function Report() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const [state, setState] = useState<ComplaintState | null>(null);
  const [request, setRequest] = useState<ServiceRequest | null>(null);
  const [category, setCategory] = useState<string | null>(null);
  const [details, setDetails] = useState('');
  const back = () => (router.canGoBack() ? router.back() : router.replace(`/request/${id}`));

  useEffect(() => {
    api.complaint(id).then(setState).catch(() => undefined);
    api.getRequest(id).then(setRequest).catch(() => undefined);
  }, [id]);

  const submit = useAction(async () => {
    const complaint = await api.fileComplaint(id, category!, details);
    setState((s) => (s ? { ...s, can_file: false, complaint } : s));
  });

  if (!state) return <Loading />;
  const tech = request?.technician;
  const company = tech?.shop_name ?? 'the company';

  if (state.complaint) {
    const c = state.complaint;
    return (
      <Screen footer={<Button label="Done" onPress={back} />}>
        <StepHeader onBack={back} />
        <Title sub={`Sent to ${company} and the ${APP_NAME} team`}>Report sent</Title>
        <Card style={{ gap: 8 }}>
          <Row style={{ justifyContent: 'space-between' }}>
            <Body style={{ fontWeight: '700' }}>{c.category_label}</Body>
            <Badge label={c.status === 'resolved' ? 'Resolved' : 'Open'} tone={c.status === 'resolved' ? 'success' : 'amber'} />
          </Row>
          <Muted>{c.details}</Muted>
          <Muted>{new Date(c.created_at).toLocaleString()}</Muted>
        </Card>
        {c.shop_response ? (
          <Card tone="soft" style={{ gap: 6 }}>
            <Body style={{ fontWeight: '700' }}>Reply from {company}</Body>
            <Body>{c.shop_response}</Body>
          </Card>
        ) : (
          <Muted>{company} will look into it. Their reply will show here.</Muted>
        )}
      </Screen>
    );
  }

  if (!state.can_file) {
    return (
      <Screen footer={<Button label="Back" onPress={back} />}>
        <StepHeader onBack={back} />
        <Title>Report a problem</Title>
        <Card tone="muted"><Muted>You can report a technician once one is assigned, up to 30 days after the job.</Muted></Card>
      </Screen>
    );
  }

  return (
    <Screen footer={
      <Button label="Send report" busy={submit.busy} disabled={!category || details.trim().length < 10}
        onPress={() => submit.run()} />
    }>
      <StepHeader onBack={back} />
      <Title sub={`About ${tech?.name ?? 'your technician'}. It goes to ${company} and to the ${APP_NAME} team; ${tech?.first_name ?? 'the technician'} won't see it.`}>
        Report a problem
      </Title>
      <View style={{ gap: 8 }} accessibilityRole="radiogroup" accessibilityLabel="What went wrong?">
        <Body style={{ fontWeight: '700' }}>What went wrong?</Body>
        {Object.entries(state.categories).map(([key, label]) => {
          const selected = category === key;
          return (
            <Pressable key={key} accessibilityRole="radio" accessibilityState={{ checked: selected }}
              onPress={() => setCategory(key)}
              style={{ flexDirection: 'row', alignItems: 'center', gap: 10, padding: 12, borderRadius: 12,
                borderWidth: 1.5, borderColor: selected ? colors.primary : colors.line,
                backgroundColor: selected ? colors.primarySoft : colors.surface }}>
              <View style={{ width: 20, height: 20, borderRadius: 10, borderWidth: 2,
                borderColor: selected ? colors.primary : colors.faint, alignItems: 'center', justifyContent: 'center' }}>
                {selected ? <View style={{ width: 10, height: 10, borderRadius: 5, backgroundColor: colors.primary }} /> : null}
              </View>
              <Text style={{ color: colors.ink, fontWeight: selected ? '700' : '500' }}>{label}</Text>
            </Pressable>
          );
        })}
      </View>
      <Field label="What happened?" value={details} onChangeText={setDetails} multiline maxLength={2000}
        placeholder="Tell us what happened, with times if you can." />
      <Row style={{ alignItems: 'flex-start' }}>
        <Icon name="shield" size={18} color={colors.muted} />
        <Muted style={{ flex: 1 }}>If you feel unsafe right now, call 911.</Muted>
      </Row>
      <ErrorText message={submit.error} />
    </Screen>
  );
}

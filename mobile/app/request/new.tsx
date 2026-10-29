import { router } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';

import { OPTION_ICONS } from '@/components/icons';
import { Button, ErrorText, Field, Label, Loading, Screen, Segmented, StepHeader, Tile, Title } from '@/components/ui';
import { api } from '@/lib/api';
import { useAction, useOptions } from '@/lib/hooks';

export default function Describe() {
  const options = useOptions();
  const [symptoms, setSymptoms] = useState<string[]>([]);
  const [description, setDescription] = useState('');
  const [urgency, setUrgency] = useState('asap');

  const create = useAction(async () => {
    const request = await api.createRequest({ symptoms, description, urgency });
    router.replace(`/request/${request.id}/photo`);
  });

  if (!options) return <Loading />;
  const toggle = (value: string) =>
    setSymptoms((s) => (s.includes(value) ? s.filter((v) => v !== value) : [...s, value]));
  const ready = symptoms.length > 0 || description.trim().length > 3;

  return (
    <Screen footer={<Button label="Next" busy={create.busy} disabled={!ready}
      onPress={() => create.run()} />}>
      <StepHeader step={1} />
      <Title>What's going wrong?</Title>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
        {options.symptoms.map((o) => (
          <Tile key={o.value} label={o.label} icon={OPTION_ICONS[o.value] ?? 'wrench'}
            selected={symptoms.includes(o.value)} onPress={() => toggle(o.value)} />
        ))}
      </View>
      <Field label="Add details (optional)" value={description} onChangeText={setDescription}
        placeholder="e.g. AC runs but blows warm air since yesterday" multiline maxLength={2000} />
      <Label>How soon do you need help?</Label>
      <Segmented options={options.urgency} value={urgency} onChange={setUrgency} />
      <ErrorText message={create.error} />
    </Screen>
  );
}

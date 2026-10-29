import { router } from 'expo-router';
import { useState } from 'react';

import { Icon } from '@/components/icons';
import { colors } from '@/components/theme';
import { Button, Card, Checkbox, ErrorText, Field, Muted, Row, Screen, Title } from '@/components/ui';
import { api } from '@/lib/api';
import { nextOnboardingRoute, useAuth } from '@/lib/auth';
import { useAction } from '@/lib/hooks';

export default function Profile() {
  const { me, setMe } = useAuth();
  const [name, setName] = useState(me?.name ?? '');
  const [address, setAddress] = useState(me?.address ?? '');
  const [sms, setSms] = useState(me?.sms_opt_in ?? true);

  const save = useAction(async () => {
    const updated = await api.updateMe({ name, address, sms_opt_in: sms });
    setMe(updated);
    const next = nextOnboardingRoute(updated);
    router.replace(next === '/profile' ? '/home' : next);
  });

  const ready = name.trim().length > 1 && address.trim().length > 5;
  return (
    <Screen footer={<Button label="Continue" busy={save.busy} disabled={!ready}
      onPress={() => save.run()} />}>
      <Title sub="So your technician knows who and where to visit.">Almost done</Title>
      <Field label="Your name" value={name} onChangeText={setName} placeholder="First and last name"
        autoComplete="name" textContentType="name" />
      <Field label="Home address" value={address} onChangeText={setAddress}
        placeholder="Street, city, ZIP" autoComplete="street-address"
        textContentType="fullStreetAddress" />
      <Card tone="muted">
        <Row>
          <Icon name="shield" size={18} color={colors.primary} />
          <Muted style={{ flex: 1 }}>
            Your address and number are only shared with the technician you book.
          </Muted>
        </Row>
      </Card>
      <Checkbox label="Text me job updates" checked={sms} onChange={setSms}
        hint="Waitlist alerts, arrival times and receipts" />
      <ErrorText message={save.error} />
    </Screen>
  );
}

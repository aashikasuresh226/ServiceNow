import { router } from 'expo-router';
import { useEffect, useState } from 'react';

import { Icon } from '@/components/icons';
import { colors } from '@/components/theme';
import { Button, Card, Checkbox, ErrorText, Field, Muted, Row, Screen, Title } from '@/components/ui';
import { api } from '@/lib/api';
import { nextOnboardingRoute, useAuth } from '@/lib/auth';
import { formatPhone } from '@/lib/format';
import { useAction, useOptions } from '@/lib/hooks';

export default function Profile() {
  const { me, setMe } = useAuth();
  const options = useOptions();
  const [name, setName] = useState(me?.name ?? '');
  const [address, setAddress] = useState(me?.address ?? '');
  const [phone, setPhone] = useState('');
  const [sms, setSms] = useState(me?.sms_opt_in ?? true);
  const needsPhone = !me?.phone;
  const [suggestedFrom, setSuggestedFrom] = useState<string | null>(null);
  // A company this homeowner is already a customer of may have their address on file.
  useEffect(() => {
    if (me?.address) return;
    api.suggestions().then((s) => {
      if (s.name) setName((current) => current || s.name!);
      if (s.address) {
        setAddress((current) => current || s.address!);
        setSuggestedFrom(s.companies[0] ?? null);
      }
    }).catch(() => undefined);
  }, [me?.address]);

  const save = useAction(async () => {
    // The address is looked up for real; an address that can't be found is rejected.
    let updated = await api.updateMe({ name, address, sms_opt_in: sms });
    if (!updated.phone) updated = await api.setPhone(phone);
    setMe(updated);
    const next = nextOnboardingRoute(updated, options);
    router.replace(next === '/profile' ? '/home' : next);
  });

  const ready = name.trim().length > 1 && address.trim().length > 8
    && (!needsPhone || phone.replace(/\D/g, '').length >= 10);
  return (
    <Screen footer={<Button label="Continue" busy={save.busy} disabled={!ready}
      onPress={() => save.run()} />}>
      <Title sub="So your technician knows who to visit, where, and how to reach you.">Your details</Title>
      <Field label="Your name" value={name} onChangeText={setName} placeholder="First and last name"
        autoComplete="name" textContentType="name" />
      <Field label="Home address" value={address} onChangeText={setAddress}
        placeholder="123 Main St, Atlanta, GA 30303" autoComplete="street-address"
        textContentType="fullStreetAddress" />
      <Muted style={{ marginTop: -8 }}>
        {suggestedFrom ? `Filled in from ${suggestedFrom}'s records. Change it if it's not right.` : 'Include the street number, city, state and ZIP.'}
      </Muted>
      {needsPhone ? (
        <>
          <Field label="Mobile number" value={phone} onChangeText={setPhone}
            placeholder="(404) 555-0123" keyboardType="phone-pad" autoComplete="tel"
            textContentType="telephoneNumber" />
          <Muted style={{ marginTop: -8 }}>Your technician uses it to reach you.</Muted>
        </>
      ) : (
        <Row>
          <Icon name="phone" size={16} color={colors.muted} />
          <Muted>{formatPhone(me?.phone)}</Muted>
        </Row>
      )}
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

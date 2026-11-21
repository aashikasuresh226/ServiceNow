/** Technician account: photo (customers see it), mobile number, how you sign in. */
import { router } from 'expo-router';
import { useState } from 'react';

import { ProfilePhoto } from '@/components/ProfilePhoto';
import { Button, Card, ErrorText, Field, KeyValue, Muted, Screen, StepHeader, Title } from '@/components/ui';
import { techApi } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { formatPhone } from '@/lib/format';
import { useAction } from '@/lib/hooks';

const SIGN_IN = {
  authenticator: 'Authenticator app (lost it? use a backup code or “Email me a recovery link” on the sign-in screen)',
  email: 'A link emailed to you each time',
  google: 'Google',
};

export default function TechAccount() {
  const { tech, refreshTech, signOutTech } = useAuth();
  const [phone, setPhone] = useState(tech?.phone ? formatPhone(tech.phone) : '');
  const [saved, setSaved] = useState(false);
  const save = useAction(async () => {
    await techApi.updateMe({ phone });
    await refreshTech();
    setSaved(true);
  });
  if (!tech) return null;
  return (
    <Screen>
      <StepHeader />
      <Title sub={tech.shop_name}>Your account</Title>
      <Card>
        <ProfilePhoto uri={tech.photo_url} name={tech.name}
          hint="Customers see your photo when you're on the way, so they know who's at the door."
          onPick={async (uri, type) => { await techApi.setPhoto(uri, type); await refreshTech(); }}
          onRemove={async () => { await techApi.removePhoto(); await refreshTech(); }} />
      </Card>
      <Card style={{ gap: 10 }}>
        <KeyValue k="Name" v={tech.name} />
        <KeyValue k="Email" v={tech.email ?? '—'} />
        <Muted>Your name and email are set by {tech.shop_name}. Ask them to change these.</Muted>
        <Field label="Mobile number" value={phone} onChangeText={(v) => { setSaved(false); save.setError(null); setPhone(v); }}
          keyboardType="phone-pad" autoComplete="tel" placeholder="(404) 555-0123" />
        <ErrorText message={save.error} />
        <Button label={saved ? 'Saved' : 'Save number'} variant="secondary" busy={save.busy} onPress={() => save.run()} />
      </Card>
      <Card style={{ gap: 4 }}>
        <KeyValue k="Sign in with" v="" />
        <Muted>{SIGN_IN[tech.sign_in]}</Muted>
      </Card>
      <Button label="Sign out" variant="danger" icon="logout"
        onPress={async () => { await signOutTech(); router.replace('/tech/sign-in'); }} />
    </Screen>
  );
}

import { router } from 'expo-router';
import { useState } from 'react';

import { Icon } from '@/components/icons';
import { colors } from '@/components/theme';
import { EmailSent } from '@/components/EmailSent';
import { Body, Button, Card, ErrorText, Field, KeyValue, Muted, Row, Screen, StepHeader, Title } from '@/components/ui';
import { api, type LinkSent } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { formatPhone } from '@/lib/format';
import { useAction, useOptions } from '@/lib/hooks';

export default function Account() {
  const { me, signOut } = useAuth();
  const options = useOptions();
  const [email, setEmail] = useState('');
  const [sent, setSent] = useState<LinkSent | null>(null);
  const addEmail = useAction(async () => {
    if (!/^\S+@\S+\.\S+$/.test(email.trim())) throw new Error('Enter your email address');
    setSent(await api.addEmail(email.trim()));
  });
  if (!me) return null;
  return (
    <Screen>
      <StepHeader />
      <Title>Account</Title>
      <Card>
        <KeyValue k="Name" v={me.name ?? '—'} />
        <KeyValue k="Phone" v={formatPhone(me.phone)} />
        {me.email ? <KeyValue k="Email" v={me.email} /> : null}
        <Muted>{me.address}</Muted>
        <Button label="Edit details" variant="secondary" onPress={() => router.push('/profile')} />
      </Card>
      {!me.email ? (
        <Card style={{ gap: 8 }}>
          <Row>
            <Icon name="shield" size={20} color={colors.primary} />
            <Body style={{ flex: 1, fontWeight: '700' }}>Add a recovery email</Body>
          </Row>
          {sent ? (
            <EmailSent sent={sent} what="confirmation link" onResend={() => addEmail.run()} resending={addEmail.busy} />
          ) : (
            <>
              <Muted>If you lose the phone with your authenticator app, we'll email you a link to get back in.</Muted>
              <Field label="Email address" value={email} onChangeText={(v) => { addEmail.setError(null); setEmail(v); }}
                placeholder="you@example.com" keyboardType="email-address" autoComplete="email" autoCapitalize="none" />
              <ErrorText message={addEmail.error} />
              <Button label="Send confirmation link" variant="secondary" icon="mail" busy={addEmail.busy}
                onPress={() => addEmail.run()} />
            </>
          )}
        </Card>
      ) : null}
      {options?.features.payments ? (
      <Card>
        <Row>
          <Icon name="card" size={20} color={colors.primary} />
          <Body style={{ flex: 1, fontWeight: '600' }}>{me.payment_method_label ?? 'No payment method'}</Body>
        </Row>
        <Button label={me.payment_method_label ? 'Replace card' : 'Add payment method'}
          variant="secondary"
          onPress={() => router.push({ pathname: '/payment', params: { returnTo: '/account' } })} />
      </Card>
      ) : (
        <Card tone="muted">
          <Muted>In-app payments aren't switched on yet. Pay your technician's shop directly.</Muted>
        </Card>
      )}
      <Button label="Sign out" variant="danger" icon="logout"
        onPress={async () => { await signOut(); router.replace('/welcome'); }} />
    </Screen>
  );
}

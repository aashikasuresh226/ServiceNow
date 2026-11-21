/**
 * Homeowners without an authenticator app: sign in with a single-use link by email.
 *   new       a new account: their email address, then the link creates the account
 *   existing  an email account: a link to the address on file
 *   recover   lost authenticator: a recovery link (removes the old authenticator)
 */
import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';

import { EmailSent } from '@/components/EmailSent';
import { Button, ErrorText, Field, Muted, Screen, StepHeader, Title } from '@/components/ui';
import { api, type LinkSent } from '@/lib/api';
import { formatPhone } from '@/lib/format';
import { useAction } from '@/lib/hooks';

type Mode = 'new' | 'existing' | 'recover';

export default function EmailSignIn() {
  const { phone = '', mode = 'existing', hint } = useLocalSearchParams<{ phone: string; mode: Mode; hint?: string }>();
  const [email, setEmail] = useState('');
  const [sent, setSent] = useState<LinkSent | null>(null);

  const send = useAction(async () => {
    if (mode === 'new' && !/^\S+@\S+\.\S+$/.test(email.trim())) throw new Error('Enter your email address');
    setSent(mode === 'recover'
      ? await api.homeownerRecover(phone)
      : await api.homeownerEmailStart(phone, mode === 'new' ? email.trim() : undefined));
  });

  const title = mode === 'recover' ? 'Recover your account' : mode === 'new' ? 'Sign in with email' : 'Check your email';
  const sub = mode === 'recover'
    ? `Lost the phone with your authenticator app? We'll email a recovery link for ${formatPhone(phone)}. Opening it removes the old authenticator; after that you sign in with email links.`
    : mode === 'new'
      ? `No authenticator app? No problem. Each time you sign in, we'll email you a secure one-time link. New account for ${formatPhone(phone)}.`
      : `This account signs in with a link we email to ${hint ?? 'your address'}.`;

  if (sent) {
    return (
      <Screen footer={<Button label="Back" variant="secondary" onPress={() => router.back()} />}>
        <StepHeader />
        <Title sub={sub}>{mode === 'new' ? 'Check your email' : title}</Title>
        <EmailSent sent={sent} what={mode === 'recover' ? 'recovery link' : 'sign-in link'}
          onResend={() => send.run()} resending={send.busy} />
        <ErrorText message={send.error} />
      </Screen>
    );
  }
  return (
    <Screen footer={
      <Button label={mode === 'recover' ? 'Email me a recovery link' : 'Email me a sign-in link'} icon="mail"
        busy={send.busy} onPress={() => send.run()} />
    }>
      <StepHeader />
      <Title sub={sub}>{title}</Title>
      {mode === 'new' ? (
        <Field label="Email address" value={email} onChangeText={(v) => { send.setError(null); setEmail(v); }}
          placeholder="you@example.com" keyboardType="email-address" autoComplete="email" autoCapitalize="none"
          onSubmitEditing={() => send.run()} />
      ) : null}
      <ErrorText message={send.error} />
      {mode === 'new' ? <Muted>We only use it to sign you in and for account recovery.</Muted> : null}
    </Screen>
  );
}

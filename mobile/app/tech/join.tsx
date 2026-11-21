/**
 * Opened from the invite email: proves the technician owns the invited address
 * (Firebase email link), then they set up sign-in (authenticator app, or Google).
 */
import { router, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import { View } from 'react-native';

import { AuthenticatorSetup, BackupCodes, type AuthenticatorSetupData } from '@/components/AuthenticatorSetup';
import { GoogleSignIn, googleSignInAvailable } from '@/components/auth/GoogleSignIn';
import { Icon } from '@/components/icons';
import { colors } from '@/components/theme';
import { Badge, Body, Button, Card, ErrorText, Field, Loading, Muted, Row, Screen, Title } from '@/components/ui';
import { api, techApi } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { useAction, useOptions } from '@/lib/hooks';
import type { InviteInfo } from '@/lib/types';

export default function JoinAsTechnician() {
  const { t: token = '' } = useLocalSearchParams<{ t: string }>();
  const options = useOptions();
  const { signInTech } = useAuth();
  const [info, setInfo] = useState<InviteInfo | null>(null);
  const [claim, setClaim] = useState<string | null>(null);
  const [fatal, setFatal] = useState<string | null>(null);
  const [phone, setPhone] = useState('');
  const [setup, setSetup] = useState<AuthenticatorSetupData | null>(null);
  const [code, setCode] = useState('');
  const [backupCodes, setBackupCodes] = useState<string[] | null>(null);
  const ran = useRef(false);

  // Opening the emailed link is the proof: confirm it right away.
  useEffect(() => {
    if (!options || ran.current) return;
    ran.current = true;
    (async () => {
      try {
        const invite = await techApi.inviteInfo(token);
        setInfo(invite);
        setClaim((await techApi.verifyInviteEmail(token)).claim);
      } catch (e) {
        setFatal(e instanceof Error && e.message ? e.message : 'This invite link is not valid.');
      }
    })();
  }, [options, token]);

  const start = useAction(async () => {
    if (phone.replace(/\D/g, '').length < 10) throw new Error('Enter your 10-digit mobile number');
    setSetup(await techApi.inviteAuthenticator(token, claim!));
  });
  const accept = useAction(async () => {
    const session = await techApi.acceptInvite({ token, claim: claim!, phone, setup_token: setup!.setup_token, code });
    await signInTech(session);
    setBackupCodes(session.backup_codes);
  });
  const useEmail = useAction(async () => {
    if (phone.replace(/\D/g, '').length < 10) throw new Error('Enter your 10-digit mobile number');
    await signInTech(await techApi.acceptInvite({ token, claim: claim!, phone, email_sign_in: true }));
    router.replace('/tech');
  });
  const google = useAction(async (idToken: string) => {
    await signInTech(await techApi.acceptInvite({ token, claim: claim!, google_id_token: idToken }));
    router.replace('/tech');
  });
  const getNonce = useCallback(async () => (await api.googleNonce()).nonce, []);

  if (fatal) {
    return (
      <Screen>
        <Title sub={fatal}>Invite can't be used</Title>
        <Muted>Ask your company to send a new invite from their HVAC Connect portal.</Muted>
        <Button label="Technician sign-in" variant="secondary" onPress={() => router.replace('/tech/sign-in')} />
      </Screen>
    );
  }
  if (!info || !claim) return <Loading label="Confirming your invite…" />;

  if (backupCodes) {
    return (
      <Screen footer={<Button label="I saved my backup codes" onPress={() => router.replace('/tech')} />}>
        <Title sub="You're in. Next time: your number or email, plus the code from your authenticator app.">
          Save your backup codes
        </Title>
        <BackupCodes codes={backupCodes} />
      </Screen>
    );
  }

  const googleClientId = options?.features.google_client_id;
  const devEmail = options?.features.email_links === 'development';
  return (
    <Screen footer={
      setup ? (
        <Button label="Verify and start" busy={accept.busy} disabled={code.length !== 6} onPress={() => accept.run()} />
      ) : (
        <Button label="Set up sign-in" icon="shield" busy={start.busy} onPress={() => start.run()} />
      )
    }>
      <Title sub={`${info.shop_name} added you to their team.`}>Join {info.shop_name}</Title>
      <Card tone="soft" style={{ gap: 6 }}>
        <Row>
          <Icon name="check" size={18} color={colors.success} strokeWidth={3} />
          <Body style={{ fontWeight: '700', flex: 1 }}>{info.email} confirmed</Body>
        </Row>
        {devEmail ? <Row><Badge label="TEST MODE" tone="amber" /><Muted style={{ flex: 1 }}>Email links aren't set up (Firebase), so opening this link counted.</Muted></Row> : null}
      </Card>
      <Card style={{ gap: 4 }}>
        <Body style={{ fontWeight: '700' }}>What {info.shop_name} lets you do</Body>
        <Muted>{info.can_respond_offers ? '✓ Accept or decline job offers' : '• The office accepts jobs for you'}</Muted>
        <Muted>{info.can_contact_customers ? '✓ Message and call customers' : '• The office talks to customers'}</Muted>
        <Muted>{info.schedule_view === 'full' ? '✓ See your full day' : '• See your next job'}</Muted>
      </Card>
      {setup ? (
        <AuthenticatorSetup setup={setup} code={code} onCode={(v) => { accept.setError(null); setCode(v); }}
          error={accept.error} />
      ) : (
        <View style={{ gap: 12 }}>
          <Body style={{ fontWeight: '700' }}>How will you sign in?</Body>
          {googleClientId && googleSignInAvailable() ? (
            <>
              <GoogleSignIn clientId={googleClientId} getNonce={getNonce} onCredential={(t) => google.run(t)} />
              <Muted>Use the Google account for {info.email}.</Muted>
              <ErrorText message={google.error} />
            </>
          ) : null}
          <Field label="Mobile number" value={phone} onChangeText={setPhone} placeholder="(404) 555-0123"
            keyboardType="phone-pad" autoComplete="tel" onSubmitEditing={() => start.run()} />
          <Muted>Customers and the office reach you on it. You'll sign in with a free authenticator app (no texts).</Muted>
          <ErrorText message={start.error} />
          <Button label={`No authenticator? Use email links (${info.email})`} variant="secondary" icon="mail"
            busy={useEmail.busy} onPress={() => useEmail.run()} />
          <ErrorText message={useEmail.error} />
          <Muted>Location is shared only while you're driving to a job, and only with that customer.</Muted>
        </View>
      )}
    </Screen>
  );
}


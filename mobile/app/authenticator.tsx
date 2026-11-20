/** New homeowner: set up the authenticator app, then save the backup codes. */
import { router } from 'expo-router';
import { useEffect, useState } from 'react';

import { AuthenticatorSetup, BackupCodes } from '@/components/AuthenticatorSetup';
import { Button, Screen, StepHeader, Title } from '@/components/ui';
import { api } from '@/lib/api';
import { nextOnboardingRoute, useAuth } from '@/lib/auth';
import { formatPhone } from '@/lib/format';
import { useAction, useOptions } from '@/lib/hooks';
import { getPendingSetup, setPendingSetup } from '@/lib/pendingSetup';
import type { Homeowner } from '@/lib/types';

export default function AuthenticatorScreen() {
  const options = useOptions();
  const { signIn } = useAuth();
  const [pending] = useState(getPendingSetup);
  const [code, setCode] = useState('');
  const [backup, setBackup] = useState<{ codes: string[]; me: Homeowner } | null>(null);

  useEffect(() => {
    if (!pending) router.replace('/welcome'); // e.g. the page was reloaded: start again
  }, [pending]);

  const finish = useAction(async () => {
    const session = await api.homeownerSignup(pending!.phone, pending!.setup.setup_token, code);
    const me = await signIn(session);
    setPendingSetup(null);
    setBackup({ codes: session.backup_codes, me });
  });

  if (!pending) return null;
  if (backup) {
    return (
      <Screen footer={<Button label="I saved my backup codes" onPress={() => router.replace(nextOnboardingRoute(backup.me, options))} />}>
        <Title sub="You're signed in. Next time, just enter the code from your authenticator app.">Save your backup codes</Title>
        <BackupCodes codes={backup.codes} />
      </Screen>
    );
  }
  return (
    <Screen footer={<Button label="Create my account" busy={finish.busy} disabled={code.length !== 6} onPress={() => finish.run()} />}>
      <StepHeader />
      <Title sub={`New account for ${formatPhone(pending.phone)}. Instead of texting you codes, your phone makes them.`}>
        Set up sign-in
      </Title>
      <AuthenticatorSetup setup={pending.setup} code={code} onCode={(v) => { finish.setError(null); setCode(v); }} error={finish.error} />
    </Screen>
  );
}

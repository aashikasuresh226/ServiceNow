/**
 * iOS/Android: Stripe PaymentSheet (cards, Apple Pay, Google Pay) saving a card
 * for later off-session charges. Web version: PaymentSetup.web.tsx.
 */
import { initPaymentSheet, initStripe, presentPaymentSheet } from '@stripe/stripe-react-native';
import { useEffect, useState } from 'react';
import { View } from 'react-native';

import { api, UserError } from '@/lib/api';
import { APP_NAME } from '@/lib/config';
import { useAction } from '@/lib/hooks';
import type { CardSetup, Homeowner } from '@/lib/types';

import { Button, ErrorText, Loading, Muted } from '../ui';
import { DemoCardForm } from './DemoCardForm';

export function PaymentSetup({ onSaved, submitLabel = 'Save payment method' }: {
  onSaved: (me: Homeowner) => void;
  submitLabel?: string;
}) {
  const [setup, setSetup] = useState<CardSetup | null>(null);
  const load = useAction(async () => setSetup(await api.startCardSetup()));

  useEffect(() => {
    void load.run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const present = useAction(async (s: CardSetup) => {
    await initStripe({
      publishableKey: s.publishable_key ?? '',
      merchantIdentifier: 'merchant.com.example.hvacconnect',
    });
    const init = await initPaymentSheet({
      merchantDisplayName: APP_NAME,
      customerId: s.customer_id,
      customerEphemeralKeySecret: s.ephemeral_key_secret ?? '',
      setupIntentClientSecret: s.client_secret,
      applePay: { merchantCountryCode: 'US' },
      googlePay: { merchantCountryCode: 'US', testEnv: s.publishable_key?.startsWith('pk_test') },
      returnURL: 'hvacconnect://stripe-redirect',
    });
    if (init.error) throw new UserError(init.error.message);
    const result = await presentPaymentSheet();
    if (result.error) {
      if (result.error.code === 'Canceled') return;
      throw new UserError(result.error.message);
    }
    onSaved(await api.finishCardSetup(s.setup_intent_id));
  });

  if (load.error) return <ErrorText message={load.error} />;
  if (!setup) return <Loading />;
  if (setup.provider === 'demo') {
    return <DemoCardForm setup={setup} onSaved={onSaved} submitLabel={submitLabel} />;
  }
  return (
    <View style={{ gap: 12 }}>
      <Muted>Add a card, Apple Pay or Google Pay. Secured by Stripe.</Muted>
      <ErrorText message={present.error} />
      <Button label={submitLabel} icon="lock" busy={present.busy} onPress={() => present.run(setup)} />
    </View>
  );
}

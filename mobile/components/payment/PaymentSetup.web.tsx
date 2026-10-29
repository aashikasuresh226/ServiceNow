/**
 * Browser: Stripe's Payment Element (cards; Apple Pay in Safari, Google Pay in Chrome)
 * confirming a SetupIntent. Falls back to the demo form when the backend runs without Stripe.
 */
import { Elements, PaymentElement, useElements, useStripe } from '@stripe/react-stripe-js';
// The 'pure' entry only fetches Stripe.js when loadStripe() is called (not in demo mode).
import { loadStripe } from '@stripe/stripe-js/pure';
import type { Stripe } from '@stripe/stripe-js';
import { useEffect, useMemo, useState } from 'react';
import { View } from 'react-native';

import { api, UserError } from '@/lib/api';
import { useAction } from '@/lib/hooks';
import type { CardSetup, Homeowner } from '@/lib/types';

import { colors } from '../theme';
import { Button, ErrorText, Loading, Muted } from '../ui';
import { DemoCardForm } from './DemoCardForm';

const stripeCache = new Map<string, Promise<Stripe | null>>();
function getStripe(key: string): Promise<Stripe | null> {
  if (!stripeCache.has(key)) stripeCache.set(key, loadStripe(key));
  return stripeCache.get(key)!;
}

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

  if (load.error) return <ErrorText message={load.error} />;
  if (!setup) return <Loading />;
  if (setup.provider === 'demo' || !setup.publishable_key) {
    return <DemoCardForm setup={setup} onSaved={onSaved} submitLabel={submitLabel} />;
  }
  return <StripeForm setup={setup} onSaved={onSaved} submitLabel={submitLabel} />;
}

function StripeForm({ setup, onSaved, submitLabel }: {
  setup: CardSetup;
  onSaved: (me: Homeowner) => void;
  submitLabel: string;
}) {
  const stripePromise = useMemo(() => getStripe(setup.publishable_key!), [setup.publishable_key]);
  return (
    <Elements
      stripe={stripePromise}
      options={{
        clientSecret: setup.client_secret,
        appearance: {
          theme: 'stripe',
          variables: { colorPrimary: colors.primary, borderRadius: '12px' },
        },
      }}
    >
      <ConfirmForm setup={setup} onSaved={onSaved} submitLabel={submitLabel} />
    </Elements>
  );
}

function ConfirmForm({ setup, onSaved, submitLabel }: {
  setup: CardSetup;
  onSaved: (me: Homeowner) => void;
  submitLabel: string;
}) {
  const stripe = useStripe();
  const elements = useElements();
  const save = useAction(async () => {
    if (!stripe || !elements) return;
    const result = await stripe.confirmSetup({
      elements,
      redirect: 'if_required',
      confirmParams: { return_url: window.location.href },
    });
    if (result.error) throw new UserError(result.error.message ?? 'Card setup failed');
    onSaved(await api.finishCardSetup(result.setupIntent?.id ?? setup.setup_intent_id));
  });
  return (
    <View style={{ gap: 12 }}>
      <Muted>Secured by Stripe. You won't be charged until a job is done.</Muted>
      <div style={{ minHeight: 120 }}>
        <PaymentElement options={{ layout: 'tabs' }} />
      </div>
      <ErrorText message={save.error} />
      <Button label={submitLabel} icon="lock" busy={save.busy} disabled={!stripe}
        onPress={() => save.run()} />
    </View>
  );
}

/**
 * Demo-mode stand-in for Stripe's card form (used when the backend runs with
 * HVAC_PAYMENTS_PROVIDER=fake). Clearly labeled; no card data is stored anywhere.
 */
import { useState } from 'react';
import { View } from 'react-native';

import { api } from '@/lib/api';
import { useAction } from '@/lib/hooks';
import type { CardSetup, Homeowner } from '@/lib/types';

import { Badge, Button, ErrorText, Field, Muted, Row } from '../ui';

export function DemoCardForm({ setup, onSaved, submitLabel }: {
  setup: CardSetup;
  onSaved: (me: Homeowner) => void;
  submitLabel: string;
}) {
  const [number, setNumber] = useState('4242 4242 4242 4242');
  const [expiry, setExpiry] = useState('12 / 30');
  const [cvc, setCvc] = useState('123');
  const [zip, setZip] = useState('30303');

  const save = useAction(async (card: string) => {
    await api.demoCard(setup.setup_intent_id, card);
    onSaved(await api.finishCardSetup(setup.setup_intent_id));
  });

  return (
    <View style={{ gap: 12 }}>
      <Row>
        <Badge label="DEMO PAYMENTS" tone="amber" />
        <Muted>Test card prefilled. Nothing is charged.</Muted>
      </Row>
      <Row style={{ gap: 8 }}>
        <Button label="Apple Pay" variant="dark" style={{ flex: 1 }}
          onPress={() => save.run('4242424242424242')} disabled={save.busy} />
        <Button label="Google Pay" variant="secondary" style={{ flex: 1 }}
          onPress={() => save.run('4242424242424242')} disabled={save.busy} />
      </Row>
      <Muted style={{ textAlign: 'center' }}>or add a card</Muted>
      <Field label="Card number" value={number} onChangeText={setNumber} keyboardType="number-pad"
        autoComplete="cc-number" />
      <Row style={{ gap: 8 }}>
        <View style={{ flex: 1 }}>
          <Field label="Expiry" value={expiry} onChangeText={setExpiry} placeholder="MM / YY" />
        </View>
        <View style={{ flex: 1 }}>
          <Field label="CVC" value={cvc} onChangeText={setCvc} keyboardType="number-pad" />
        </View>
        <View style={{ flex: 1 }}>
          <Field label="ZIP" value={zip} onChangeText={setZip} keyboardType="number-pad" />
        </View>
      </Row>
      <ErrorText message={save.error} />
      <Button label={submitLabel} icon="lock" busy={save.busy} onPress={() => save.run(number)} />
    </View>
  );
}

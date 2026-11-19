/**
 * Public page for a shared link: /p/technician/<id> or /p/shop/<id>.
 * Shows the company / technician with ratings and phone, and lets a friend book
 * them (signing up first if needed). No customer data is shown.
 */
import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { Linking, Text, View } from 'react-native';

import { Icon } from '@/components/icons';
import { Avatar } from '@/components/illustrations';
import { colors } from '@/components/theme';
import { Badge, Body, Button, Card, ErrorText, Loading, Muted, Row, Screen } from '@/components/ui';
import { api } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { rememberChoice } from '@/lib/choice';
import { APP_NAME } from '@/lib/config';
import { labelFor, useAction, useOptions } from '@/lib/hooks';
import type { PublicProvider } from '@/lib/types';

export default function ProviderPage() {
  const { kind, id } = useLocalSearchParams<{ kind: string; id: string }>();
  const options = useOptions();
  const { tokens } = useAuth();
  const [card, setCard] = useState<PublicProvider | null>(null);
  const load = useAction(async () => {
    setCard(kind === 'shop' ? await api.publicShop(id) : await api.publicTechnician(id));
  });
  useEffect(() => { void load.run(); }, [kind, id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!card) {
    return load.error ? (
      <Screen><ErrorText message={load.error} /></Screen>
    ) : <Loading />;
  }
  const shop = card.kind === 'shop' ? card : card.shop;
  const name = card.name;
  const book = async () => {
    await rememberChoice({ kind: card.kind, id: card.id, name });
    router.replace(tokens ? '/request/new' : '/welcome');
  };

  return (
    <Screen footer={
      <>
        <Button label={`Book ${name.split(' ')[0]}`} icon="wrench" disabled={!shop.taking_requests}
          onPress={() => void book()} />
        {shop.phone ? (
          <Button label={`Call ${shop.name}`} icon="phone" variant="secondary"
            onPress={() => void Linking.openURL(`tel:${shop.phone}`)} />
        ) : null}
      </>
    }>
      <Muted style={{ textAlign: 'center' }}>Recommended to you on {APP_NAME}</Muted>
      <Card style={{ alignItems: 'center', gap: 8, paddingVertical: 24 }}>
        {card.kind === 'technician' ? <Avatar size={72} name={card.name} /> : (
          <View style={{ width: 72, height: 72, borderRadius: 20, backgroundColor: colors.primarySoft,
            alignItems: 'center', justifyContent: 'center' }}>
            <Icon name="building" size={34} color={colors.primary} />
          </View>
        )}
        <Text style={{ fontSize: 24, fontWeight: '800', color: colors.ink, textAlign: 'center' }}>{name}</Text>
        {card.kind === 'technician' ? <Body>{shop.name}</Body> : null}
        <Row style={{ gap: 6 }}>
          <Icon name="star" size={16} color={colors.amber} />
          <Body>{card.rating ? `${card.rating.toFixed(1)} · ${card.rating_count} rating${card.rating_count === 1 ? '' : 's'}` : 'No ratings yet'}</Body>
        </Row>
        {!shop.taking_requests ? <Badge label="Not taking requests right now" tone="amber" /> : null}
      </Card>
      {card.kind === 'technician' && (card.certifications.length || card.equipment_types.length) ? (
        <Card style={{ gap: 6 }}>
          {card.certifications.length ? (
            <Muted>Certified: {card.certifications.map((c) => labelFor(options, 'certifications', c)).join(', ')}</Muted>
          ) : null}
          {card.equipment_types.length ? (
            <Muted>Works on: {card.equipment_types.map((e) => labelFor(options, 'equipment_types', e)).join(', ')}</Muted>
          ) : null}
        </Card>
      ) : null}
      <Card tone="muted" style={{ gap: 6 }}>
        <Row><Icon name="building" size={16} color={colors.primary} /><Body>{shop.name}</Body></Row>
        {shop.area ? <Row><Icon name="mapPin" size={16} color={colors.primary} /><Body>{shop.area}</Body></Row> : null}
        {shop.phone ? <Row><Icon name="phone" size={16} color={colors.primary} /><Body selectable>{shop.phone}</Body></Row> : null}
        {card.kind === 'technician' && shop.rating ? (
          <Muted>Company rating ★ {shop.rating.toFixed(1)} ({shop.rating_count})</Muted>
        ) : null}
      </Card>
      <Muted>Booking takes about a minute: describe the problem, snap your unit, and we'll
        book {name.split(' ')[0]} at their earliest opening.</Muted>
    </Screen>
  );
}

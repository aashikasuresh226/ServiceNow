/** Opened from a company's invite (text, email, QR code): who invited you, then sign up. */
import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { Text, View } from 'react-native';

import { Icon, type IconName } from '@/components/icons';
import { colors } from '@/components/theme';
import { Body, Button, Card, Loading, Muted, Row, Screen } from '@/components/ui';
import { api } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { APP_NAME } from '@/lib/config';
import { acceptPendingInvite, savePendingInvite } from '@/lib/invite';

const PERKS: [IconName, string][] = [
  ['calendar', 'Book a visit in a minute, from a photo of your unit'],
  ['truck', 'See when your technician is on the way'],
  ['chat', 'Message your technician and approve prices in the app'],
];

export default function Join() {
  const { code } = useLocalSearchParams<{ code: string }>();
  const { tokens } = useAuth();
  const [shop, setShop] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.inviteInfo(code)
      .then(async (info) => {
        setShop(info.shop_name);
        await savePendingInvite({ code, shopName: info.shop_name });
      })
      .catch(() => setError("This invite link isn't valid. You can still use the app."));
  }, [code]);

  const go = async () => {
    if (tokens) {
      await acceptPendingInvite();
      router.replace('/home');
    } else {
      router.replace('/welcome');
    }
  };

  if (!shop && !error) return <Loading />;
  return (
    <Screen footer={<Button label="Get started" onPress={() => { void go(); }} />}>
      <Card tone="brand" style={{ alignItems: 'center', gap: 10, paddingVertical: 24 }}>
        <View style={{ width: 56, height: 56, borderRadius: 16, backgroundColor: colors.surface,
          alignItems: 'center', justifyContent: 'center' }}>
          <Icon name="building" size={28} color={colors.primary} />
        </View>
        <Text style={{ fontSize: 24, fontWeight: '800', color: '#FFFFFF', textAlign: 'center' }}>
          {shop ? `${shop} invited you` : APP_NAME}
        </Text>
        <Muted style={{ textAlign: 'center', color: colors.primaryTint }}>
          {shop ? `${shop} uses ${APP_NAME} for visits and updates.` : error}
        </Muted>
      </Card>
      <View style={{ gap: 12 }}>
        {PERKS.map(([icon, text]) => (
          <Row key={text} style={{ alignItems: 'flex-start' }}>
            <Icon name={icon} size={20} color={colors.primary} />
            <Body style={{ flex: 1 }}>{text}</Body>
          </Row>
        ))}
      </View>
      {shop ? (
        <Muted>Use the mobile number {shop} has for you and we'll connect your account to them.</Muted>
      ) : null}
    </Screen>
  );
}

import { router } from 'expo-router';

import { Icon } from '@/components/icons';
import { colors } from '@/components/theme';
import { Body, Button, Card, KeyValue, Muted, Row, Screen, StepHeader, Title } from '@/components/ui';
import { useAuth } from '@/lib/auth';
import { formatPhone } from '@/lib/format';

export default function Account() {
  const { me, signOut } = useAuth();
  if (!me) return null;
  return (
    <Screen>
      <StepHeader />
      <Title>Account</Title>
      <Card>
        <KeyValue k="Name" v={me.name ?? '—'} />
        <KeyValue k="Phone" v={formatPhone(me.phone)} />
        <Muted>{me.address}</Muted>
        <Button label="Edit details" variant="secondary" onPress={() => router.push('/profile')} />
      </Card>
      <Card>
        <Row>
          <Icon name="card" size={20} color={colors.primary} />
          <Body style={{ flex: 1, fontWeight: '600' }}>{me.payment_method_label ?? 'No payment method'}</Body>
        </Row>
        <Button label={me.payment_method_label ? 'Replace card' : 'Add payment method'}
          variant="secondary"
          onPress={() => router.push({ pathname: '/payment', params: { returnTo: '/account' } })} />
      </Card>
      <Button label="Sign out" variant="danger" icon="logout"
        onPress={async () => { await signOut(); router.replace('/welcome'); }} />
    </Screen>
  );
}

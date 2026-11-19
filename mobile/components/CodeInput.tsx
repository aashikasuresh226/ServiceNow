/** 6-digit code field with a test-mode hint when texts aren't set up. */
import { Text, TextInput, View } from 'react-native';

import { colors, radius } from './theme';
import { Badge, Muted, Row } from './ui';

export function CodeInput({ value, onChange, devCode, phoneLabel }: {
  value: string;
  onChange: (code: string) => void;
  devCode?: string | null;
  phoneLabel: string;
}) {
  return (
    <View style={{ gap: 8 }}>
      <Text style={{ fontWeight: '600', color: colors.ink }}>Code sent to {phoneLabel}</Text>
      <TextInput value={value} onChangeText={(v) => onChange(v.replace(/\D/g, '').slice(0, 6))}
        keyboardType="number-pad" autoComplete="one-time-code" textContentType="oneTimeCode"
        accessibilityLabel="6-digit code" placeholder="123456" placeholderTextColor={colors.faint} maxLength={6}
        style={{
          borderWidth: 1.5, borderColor: colors.primary, borderRadius: radius.md, height: 56,
          fontSize: 26, letterSpacing: 8, textAlign: 'center', color: colors.ink, fontWeight: '700',
        }} />
      {devCode ? (
        <Row>
          <Badge label="TEST MODE" tone="amber" />
          <Muted style={{ flex: 1 }}>Texting isn't set up, so the code is filled in for you.</Muted>
        </Row>
      ) : null}
    </View>
  );
}

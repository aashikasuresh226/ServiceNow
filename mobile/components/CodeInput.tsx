/** Code field for the authenticator app's 6-digit code, or (when allowed) a backup code. */
import { useState } from 'react';
import { Text, TextInput, View } from 'react-native';

import { colors, radius } from './theme';
import { TextLink } from './ui';

export function CodeInput({ value, onChange, label = 'Code from your authenticator app', allowBackup = false, onSubmit }: {
  value: string;
  onChange: (code: string) => void;
  label?: string;
  allowBackup?: boolean;
  onSubmit?: () => void;
}) {
  const [backup, setBackup] = useState(false);
  return (
    <View style={{ gap: 8 }}>
      <Text style={{ fontWeight: '600', color: colors.ink }}>{backup ? 'Backup code' : label}</Text>
      <TextInput
        value={value}
        onChangeText={(v) => onChange(backup ? v.toUpperCase().replace(/[^A-Z0-9-]/g, '').slice(0, 9) : v.replace(/\D/g, '').slice(0, 6))}
        keyboardType={backup ? 'default' : 'number-pad'}
        autoCapitalize="characters"
        autoComplete="one-time-code"
        textContentType="oneTimeCode"
        accessibilityLabel={backup ? 'Backup code' : '6-digit code'}
        placeholder={backup ? 'ABCD-EFGH' : '123456'}
        placeholderTextColor={colors.faint}
        maxLength={backup ? 9 : 6}
        onSubmitEditing={onSubmit}
        style={{
          borderWidth: 1.5, borderColor: colors.primary, borderRadius: radius.md, height: 56,
          fontSize: 26, letterSpacing: backup ? 3 : 8, textAlign: 'center', color: colors.ink, fontWeight: '700',
        }} />
      {allowBackup ? (
        <TextLink label={backup ? 'Use my authenticator app instead' : 'Lost your phone? Use a backup code'}
          color={colors.muted} onPress={() => { setBackup(!backup); onChange(''); }} />
      ) : null}
    </View>
  );
}

/** A 6-digit authenticator code, or a backup code like ABCD-EFGH. */
export function codeReady(code: string): boolean {
  return /^\d{6}$/.test(code) || /^[A-Z0-9]{4}-?[A-Z0-9]{4}$/.test(code);
}

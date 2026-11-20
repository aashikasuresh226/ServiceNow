/** Set up sign-in with an authenticator app (free, no texts): add the account, then type the
 * 6-digit code it shows. Works on the same phone ("Add to authenticator app" link, or the key)
 * or from another device (QR code). */
import { useState } from 'react';
import { Linking, Platform, Text, View } from 'react-native';
import QRCode from 'react-native-qrcode-svg';

import { CodeInput } from './CodeInput';
import { Icon } from './icons';
import { colors, radius } from './theme';
import { Body, Button, Card, ErrorText, Muted, Row, TextLink } from './ui';

export type AuthenticatorSetupData = { setup_token: string; secret: string; otpauth_uri: string };

export function AuthenticatorSetup({ setup, code, onCode, error }: {
  setup: AuthenticatorSetupData;
  code: string;
  onCode: (code: string) => void;
  error?: string | null;
}) {
  const [showQr, setShowQr] = useState(Platform.OS === 'web');
  const key = setup.secret.replace(/(.{4})/g, '$1 ').trim();
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      if (Platform.OS === 'web') await navigator.clipboard.writeText(setup.secret);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };
  return (
    <View style={{ gap: 14 }}>
      <Step n={1} title="Get an authenticator app (free)">
        <Muted>
          Google Authenticator or Microsoft Authenticator from your app store. On iPhone you can also use the built-in
          Passwords app. Already have one? Use it.
        </Muted>
      </Step>
      <Step n={2} title="Add HVAC Connect to it">
        <Button label="Add to my authenticator app" icon="shield" variant="secondary"
          onPress={() => { void Linking.openURL(setup.otpauth_uri); }} />
        <TextLink label={showQr ? 'Hide QR code' : 'Scan a QR code from another device instead'}
          color={colors.muted} onPress={() => setShowQr(!showQr)} />
        {showQr ? (
          <View style={{ alignItems: 'center', padding: 12, backgroundColor: '#fff', borderRadius: radius.md,
            borderWidth: 1, borderColor: colors.line }} accessibilityLabel="QR code to scan with your authenticator app">
            <QRCode value={setup.otpauth_uri} size={168} />
          </View>
        ) : null}
        <Card tone="muted" style={{ gap: 4 }}>
          <Muted>Or type this key into the app (time-based):</Muted>
          <Text selectable style={{ fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace', fontSize: 15,
            color: colors.ink, letterSpacing: 1 }} accessibilityLabel={`Setup key ${setup.secret.split('').join(' ')}`}>
            {key}
          </Text>
          {Platform.OS === 'web' ? (
            <TextLink label={copied ? 'Copied' : 'Copy key'} onPress={() => { void copy(); }} />
          ) : null}
        </Card>
      </Step>
      <Step n={3} title="Type the 6-digit code it shows">
        <CodeInput value={code} onChange={onCode} label="6-digit code" />
        <ErrorText message={error} />
      </Step>
    </View>
  );
}

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <View style={{ gap: 8 }}>
      <Row style={{ gap: 8 }}>
        <View style={{ width: 24, height: 24, borderRadius: 12, backgroundColor: colors.primary,
          alignItems: 'center', justifyContent: 'center' }}>
          <Text style={{ color: '#fff', fontWeight: '700', fontSize: 13 }}>{n}</Text>
        </View>
        <Body style={{ fontWeight: '700', flex: 1 }}>{title}</Body>
      </Row>
      {children}
    </View>
  );
}

/** Shown once after setup: the codes that get you in if you lose your phone. */
export function BackupCodes({ codes }: { codes: string[] }) {
  const [copied, setCopied] = useState(false);
  return (
    <View style={{ gap: 12 }}>
      <Card tone="amber" style={{ flexDirection: 'row', alignItems: 'flex-start', gap: 10 }}>
        <Icon name="shield" size={20} color={colors.amberInk} />
        <Body style={{ flex: 1, color: colors.amberInk }}>
          Save these backup codes somewhere safe (a screenshot or your password manager). Each one signs you in once
          if you lose your phone. You won't see them again.
        </Body>
      </Card>
      <Card style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 10, justifyContent: 'center' }}>
        {codes.map((code) => (
          <Text key={code} selectable style={{ width: '45%', textAlign: 'center', fontSize: 17, letterSpacing: 1,
            fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace', color: colors.ink }}>{code}</Text>
        ))}
      </Card>
      {Platform.OS === 'web' ? (
        <TextLink label={copied ? 'Copied' : 'Copy all codes'} onPress={() => {
          void navigator.clipboard.writeText(codes.join('\n')).then(() => setCopied(true)).catch(() => undefined);
        }} />
      ) : null}
    </View>
  );
}

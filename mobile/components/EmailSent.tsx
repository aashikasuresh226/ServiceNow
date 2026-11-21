/** "Check your email" after a sign-in, recovery or confirmation link was sent. */
import { useEffect, useState } from 'react';
import { Linking, Platform, View } from 'react-native';

import { Icon } from './icons';
import { colors } from './theme';
import { Badge, Body, Button, Card, Muted, Row, TextLink } from './ui';
import type { LinkSent } from '@/lib/api';

export function openDevLink(url: string): void {
  if (Platform.OS === 'web' && typeof window !== 'undefined') window.location.assign(url);
  else void Linking.openURL(url);
}

export function EmailSent({ sent, what = 'sign-in link', note, onResend, resending }: {
  sent: LinkSent;
  what?: string;
  note?: string;
  onResend?: () => void;
  resending?: boolean;
}) {
  const [wait, setWait] = useState(30);
  useEffect(() => {
    setWait(30);
    const timer = setInterval(() => setWait((s) => (s > 0 ? s - 1 : 0)), 1000);
    return () => clearInterval(timer);
  }, [sent]);
  return (
    <View style={{ gap: 12 }}>
      <Card tone="soft" style={{ gap: 8 }}>
        <Row>
          <Icon name="mail" size={20} color={colors.primary} />
          <Body style={{ fontWeight: '700', flex: 1 }}>
            {sent.sent_to ? `We emailed a ${what} to ${sent.sent_to}` : `If the account uses email, we've sent a ${what}`}
          </Body>
        </Row>
        <Muted>
          Open it on this {Platform.OS === 'web' ? 'device' : 'phone'} to continue. It works once and expires soon.
          Not in your inbox? Check Spam or Junk.
        </Muted>
        {note ? <Muted>{note}</Muted> : null}
      </Card>
      {sent.dev_link ? (
        <Card tone="amber" style={{ gap: 6 }}>
          <Row><Badge label="TEST MODE" tone="amber" /><Muted style={{ flex: 1 }}>Email isn't set up (Firebase), so here's the link.</Muted></Row>
          <TextLink label="Open the emailed link" onPress={() => openDevLink(sent.dev_link!)} />
        </Card>
      ) : null}
      {onResend ? (
        <Button label={wait > 0 ? `Send again in ${wait}s` : 'Send again'} variant="secondary" icon="mail"
          disabled={wait > 0} busy={resending} onPress={onResend} />
      ) : null}
    </View>
  );
}

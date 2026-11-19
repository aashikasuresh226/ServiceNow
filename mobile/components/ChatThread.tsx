/** A message thread (homeowner ↔ shop/technician). Refreshes while open. */
import { useCallback, useEffect, useRef, useState } from 'react';
import type { ComponentRef } from 'react';
import { ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';

import { colors, radius } from './theme';
import { Button, ErrorText, Muted, Row } from './ui';
import { POLL_INTERVAL_MS } from '@/lib/config';
import { useAction, usePolling } from '@/lib/hooks';
import type { Message } from '@/lib/types';

export function ChatThread({ load, send, me, closed, closedNote }: {
  load: () => Promise<Message[]>;
  send: (body: string) => Promise<unknown>;
  /** Which sender is "me" (shown on the right). */
  me: Message['sender'];
  closed?: boolean;
  closedNote?: string;
}) {
  const [messages, setMessages] = useState<Message[] | null>(null);
  const [text, setText] = useState('');
  const scroller = useRef<ComponentRef<typeof ScrollView>>(null);
  const refresh = useCallback(async () => {
    try {
      setMessages(await load());
    } catch {
      // keep what we have; the next poll retries
    }
  }, [load]);
  useEffect(() => { void refresh(); }, [refresh]);
  usePolling(refresh, POLL_INTERVAL_MS, true);
  const submit = useAction(async () => {
    const body = text.trim();
    if (!body) return;
    await send(body);
    setText('');
    await refresh();
  });

  return (
    <View style={{ flex: 1, gap: 10 }}>
      <ScrollView ref={scroller} style={{ flex: 1 }} contentContainerStyle={{ gap: 8, paddingVertical: 4 }}
        onContentSizeChange={() => scroller.current?.scrollToEnd({ animated: false })}>
        {messages === null ? <Muted>Loading…</Muted> : null}
        {messages?.length === 0 ? <Muted style={{ textAlign: 'center' }}>No messages yet. Say hello.</Muted> : null}
        {messages?.map((m) => {
          const mine = m.sender === me;
          const who = m.sender === 'shop' ? `${m.sender_name ?? 'Office'} (office)` : m.sender_name
            ?? (m.sender === 'technician' ? 'Technician' : 'Customer');
          return (
            <View key={m.id} style={[styles.bubble, mine ? styles.mine : styles.theirs]}
              accessibilityLabel={`${mine ? 'You' : who}: ${m.body}`}>
              {!mine ? <Text style={styles.who}>{who}</Text> : null}
              <Text style={{ color: mine ? '#FFFFFF' : colors.ink, fontSize: 15, lineHeight: 20 }}>{m.body}</Text>
              <Text style={[styles.time, mine && { color: '#DCE5FB' }]}>
                {new Date(m.created_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}
              </Text>
            </View>
          );
        })}
      </ScrollView>
      {closed ? (
        <Muted style={{ textAlign: 'center' }}>{closedNote ?? 'This chat is closed.'}</Muted>
      ) : (
        <>
          <ErrorText message={submit.error} />
          <Row style={{ gap: 8 }}>
            <TextInput value={text} onChangeText={setText} placeholder="Message" maxLength={1000}
              accessibilityLabel="Message" style={styles.input} placeholderTextColor={colors.faint}
              onSubmitEditing={() => submit.run()} returnKeyType="send" />
            <Button label="Send" icon="send" busy={submit.busy} disabled={!text.trim()}
              onPress={() => submit.run()} style={{ paddingHorizontal: 16, flexGrow: 0, flexShrink: 0 }} />
          </Row>
        </>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  bubble: { maxWidth: '82%', paddingHorizontal: 12, paddingVertical: 8, borderRadius: radius.md },
  mine: { alignSelf: 'flex-end', backgroundColor: colors.primary, borderBottomRightRadius: 4 },
  theirs: { alignSelf: 'flex-start', backgroundColor: colors.background, borderBottomLeftRadius: 4 },
  who: { fontSize: 11, fontWeight: '700', color: colors.muted, marginBottom: 2 },
  time: { fontSize: 10, color: colors.faint, marginTop: 2, alignSelf: 'flex-end' },
  input: {
    flex: 1, minWidth: 0, minHeight: 48, borderWidth: 1, borderColor: colors.lineStrong, borderRadius: radius.md,
    paddingHorizontal: 14, fontSize: 16, color: colors.ink, backgroundColor: colors.surface,
  },
});

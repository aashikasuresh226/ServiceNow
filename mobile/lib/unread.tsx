/** New-message alerts for homeowners: polls the API, shows a banner when a message
 * arrives (tap to open the chat), keeps unread counts for badges, and on the web also
 * puts the count in the tab title and shows a browser notification when the tab is in
 * the background (if the person allowed notifications). */
import { router, usePathname } from 'expo-router';
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { Platform, Pressable, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Icon } from '@/components/icons';
import { colors } from '@/components/theme';
import { api } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { APP_NAME } from '@/lib/config';
import type { UnreadChat } from '@/lib/types';

const POLL_MS = 6000;

type Unread = { byRequest: Record<string, number>; total: number; refresh: () => void };
const UnreadContext = createContext<Unread>({ byRequest: {}, total: 0, refresh: () => undefined });
export const useUnread = () => useContext(UnreadContext);

function webNotify(chat: UnreadChat) {
  if (Platform.OS !== 'web' || typeof Notification === 'undefined') return;
  if (Notification.permission !== 'granted' || document.visibilityState === 'visible') return;
  const n = new Notification(`New message from ${chat.sender_name ?? 'your technician'}`, {
    body: chat.preview,
    tag: `chat-${chat.request_id}`,
  });
  n.onclick = () => { window.focus(); router.push(`/request/${chat.request_id}/chat`); n.close(); };
}

/** Ask once (from a button: browsers require a tap) to show alerts while the app is in the background. */
export function canAskForWebAlerts(): boolean {
  return Platform.OS === 'web' && typeof Notification !== 'undefined' && Notification.permission === 'default';
}
export async function askForWebAlerts(): Promise<boolean> {
  if (!canAskForWebAlerts()) return false;
  return (await Notification.requestPermission()) === 'granted';
}

export function UnreadProvider({ children }: { children: ReactNode }) {
  const { tokens, role } = useAuth();
  const pathname = usePathname();
  const insets = useSafeAreaInsets();
  const [chats, setChats] = useState<UnreadChat[]>([]);
  const [banner, setBanner] = useState<UnreadChat | null>(null);
  const seen = useRef<Map<string, string>>(new Map()); // request id -> newest message time seen
  const first = useRef(true);
  const path = useRef(pathname);
  path.current = pathname;

  const refresh = useCallback(async () => {
    if (!tokens || role !== 'homeowner') return;
    try {
      const data = await api.notifications();
      const fresh = data.unread_messages.filter((c) => seen.current.get(c.request_id) !== c.last_at);
      data.unread_messages.forEach((c) => seen.current.set(c.request_id, c.last_at));
      setChats(data.unread_messages);
      const newest = fresh[0];
      if (!first.current && newest) {
        if (path.current !== `/request/${newest.request_id}/chat`) {
          setBanner(newest);
          webNotify(newest);
        }
      }
      first.current = false; // messages already waiting at sign-in show as badges, not banners
    } catch {
      // offline or signed out: try again next time
    }
  }, [tokens, role]);

  useEffect(() => {
    first.current = true;
    seen.current.clear();
    setChats([]);
    if (!tokens || role !== 'homeowner') return;
    void refresh();
    const timer = setInterval(() => { void refresh(); }, POLL_MS);
    return () => clearInterval(timer);
  }, [tokens, role, refresh]);

  useEffect(() => {
    if (!banner) return;
    const timer = setTimeout(() => setBanner(null), 7000);
    return () => clearTimeout(timer);
  }, [banner]);

  const total = chats.reduce((sum, c) => sum + c.count, 0);
  useEffect(() => {
    if (Platform.OS === 'web') document.title = total ? `(${total}) ${APP_NAME}` : APP_NAME;
  }, [total]);

  const byRequest = Object.fromEntries(chats.map((c) => [c.request_id, c.count]));
  return (
    <UnreadContext.Provider value={{ byRequest, total, refresh: () => { void refresh(); } }}>
      {children}
      {banner ? (
        <View pointerEvents="box-none" style={{ position: 'absolute', top: insets.top + 8, left: 12, right: 12, alignItems: 'center' }}>
          <Pressable
            accessibilityRole="alert"
            accessibilityLabel={`New message from ${banner.sender_name ?? 'your technician'}: ${banner.preview}. Open chat`}
            onPress={() => { setBanner(null); router.push(`/request/${banner.request_id}/chat`); }}
            style={{
              width: '100%', maxWidth: 480, flexDirection: 'row', gap: 12, alignItems: 'center',
              backgroundColor: colors.ink, borderRadius: 14, paddingVertical: 12, paddingHorizontal: 14,
              shadowColor: '#000', shadowOpacity: 0.2, shadowRadius: 12, shadowOffset: { width: 0, height: 4 }, elevation: 6,
            }}>
            <View style={{ width: 34, height: 34, borderRadius: 17, backgroundColor: colors.primary, alignItems: 'center', justifyContent: 'center' }}>
              <Icon name="chat" size={18} color="#fff" />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={{ color: '#fff', fontWeight: '700' }} numberOfLines={1}>
                {banner.sender_name ?? 'Your technician'}
              </Text>
              <Text style={{ color: '#D7DBE4' }} numberOfLines={2}>{banner.preview}</Text>
            </View>
            <Text style={{ color: '#fff', fontWeight: '700' }}>Open</Text>
          </Pressable>
        </View>
      ) : null}
    </UnreadContext.Provider>
  );
}

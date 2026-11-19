/**
 * Share a recommendation to a group chat or message: the phone's share sheet when
 * there is one, or straight to Messages / WhatsApp, or copy to paste anywhere.
 */
import { Linking, Platform, Share } from 'react-native';

export async function shareSheet(message: string, title: string): Promise<'shared' | 'copied'> {
  if (Platform.OS !== 'web') {
    await Share.share({ message, title });
    return 'shared';
  }
  const nav = typeof navigator !== 'undefined' ? navigator : undefined;
  if (nav?.share) {
    try {
      await nav.share({ title, text: message });
      return 'shared';
    } catch (e) {
      if ((e as Error)?.name === 'AbortError') return 'shared';
    }
  }
  await copyText(message);
  return 'copied';
}

export async function copyText(text: string): Promise<void> {
  if (Platform.OS === 'web' && typeof navigator !== 'undefined' && navigator.clipboard) {
    await navigator.clipboard.writeText(text);
    return;
  }
  await Share.share({ message: text });
}

export function textMessage(message: string): Promise<void> {
  // iOS uses "&body=", Android and desktop apps "?body=".
  const sep = Platform.OS === 'ios' ? '&' : '?';
  return Linking.openURL(`sms:${sep}body=${encodeURIComponent(message)}`);
}

export function whatsApp(message: string): Promise<void> {
  return Linking.openURL(`https://wa.me/?text=${encodeURIComponent(message)}`);
}

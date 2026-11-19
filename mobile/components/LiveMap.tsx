/** Live technician position. Native version: open it in the phone's maps app. */
import { Linking, Platform, Pressable, Text, View } from 'react-native';

import { Icon } from './icons';
import { colors } from './theme';

export function LiveMap({ lat, lng, height = 220, label }: {
  lat: number;
  lng: number;
  height?: number;
  label: string;
}) {
  const url = Platform.OS === 'ios'
    ? `http://maps.apple.com/?ll=${lat},${lng}&q=${encodeURIComponent(label)}`
    : `geo:${lat},${lng}?q=${lat},${lng}(${encodeURIComponent(label)})`;
  return (
    <Pressable accessibilityRole="link" accessibilityLabel={`${label}. Open in Maps`} onPress={() => Linking.openURL(url)}
      style={{ height, backgroundColor: colors.primarySoft, alignItems: 'center', justifyContent: 'center', gap: 8 }}>
      <Icon name="mapPin" size={36} color={colors.primary} />
      <View style={{ alignItems: 'center' }}>
        <Text style={{ fontWeight: '700', color: colors.ink }}>{label}</Text>
        <Text style={{ color: colors.primary, fontWeight: '600' }}>Open in Maps</Text>
      </View>
    </Pressable>
  );
}

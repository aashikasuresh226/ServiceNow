/** Live technician position on an OpenStreetMap map (free, no key). Web version. */
import { createElement } from 'react';
import { View } from 'react-native';

export function LiveMap({ lat, lng, height = 220, label }: {
  lat: number;
  lng: number;
  height?: number;
  label: string;
}) {
  const d = 0.012;
  const bbox = [lng - d, lat - d * 0.7, lng + d, lat + d * 0.7].map((v) => v.toFixed(5)).join(',');
  const src = `https://www.openstreetmap.org/export/embed.html?bbox=${bbox}&layer=mapnik&marker=${lat.toFixed(5)},${lng.toFixed(5)}`;
  return (
    <View style={{ height, overflow: 'hidden', backgroundColor: '#E8EEFD' }}>
      {createElement('iframe', {
        src,
        title: label,
        style: { border: 0, width: '100%', height: '100%' },
        loading: 'lazy',
        referrerPolicy: 'no-referrer',
      })}
    </View>
  );
}

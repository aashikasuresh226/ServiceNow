/** A time of day ("17:30"): the browser's own time field. */
import { createElement } from 'react';
import { View } from 'react-native';

import { colors } from './theme';

type Props = { value: string; onChange: (value: string) => void; label: string; invalid?: boolean };

export function TimeField({ value, onChange, label, invalid }: Props) {
  return (
    <View style={{ flex: 1 }}>
      {createElement('input', {
        type: 'time',
        step: 300,
        value,
        'aria-label': label,
        'aria-invalid': invalid || undefined,
        onChange: (e: { target: { value: string } }) => { if (e.target.value) onChange(e.target.value); },
        style: {
          width: '100%', boxSizing: 'border-box', font: 'inherit', fontSize: 15, color: colors.ink,
          padding: '10px 12px', borderRadius: 10, background: colors.surface,
          border: `1px solid ${invalid ? colors.danger : colors.lineStrong}`, fontVariantNumeric: 'tabular-nums',
        },
      })}
    </View>
  );
}

/** A time of day ("17:30"): the phone's own time picker. */
import DateTimePicker, { DateTimePickerAndroid } from '@react-native-community/datetimepicker';
import { Platform, Pressable, Text, View } from 'react-native';

import { Icon } from './icons';
import { colors } from './theme';
import { formatClock, parts } from '@/lib/homeTimes';

type Props = { value: string; onChange: (value: string) => void; label: string; invalid?: boolean };

function toDate(value: string): Date {
  const [h, m] = parts(value);
  const d = new Date();
  d.setHours(h, m, 0, 0);
  return d;
}

function fromDate(d: Date): string {
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

export function TimeField({ value, onChange, label, invalid }: Props) {
  if (Platform.OS === 'ios') {
    return (
      <View accessibilityLabel={label} style={{ flex: 1, alignItems: 'flex-start' }}>
        <DateTimePicker value={toDate(value)} mode="time" display="compact" minuteInterval={5}
          accentColor={colors.primary}
          onChange={(_, d) => { if (d) onChange(fromDate(d)); }} />
      </View>
    );
  }
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={`${label}: ${formatClock(value)}`}
      onPress={() => DateTimePickerAndroid.open({
        value: toDate(value), mode: 'time', is24Hour: false,
        onChange: (event, d) => { if (event.type === 'set' && d) onChange(fromDate(d)); },
      })}
      style={{ flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
        borderWidth: 1, borderColor: invalid ? colors.danger : colors.lineStrong, borderRadius: 10,
        paddingVertical: 11, paddingHorizontal: 12, backgroundColor: colors.surface }}>
      <Text style={{ fontSize: 15, color: colors.ink, fontVariant: ['tabular-nums'] }}>{formatClock(value)}</Text>
      <Icon name="clock" size={16} color={colors.faint} />
    </Pressable>
  );
}

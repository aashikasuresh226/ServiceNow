/** "What was actually wrong?": the technician's answer, saved with the job (it's what a
 * diagnosis model learns from, next to the AI's guess and the photos). */
import { Pressable, Text, View } from 'react-native';

import { colors } from './theme';
import { Body } from './ui';
import type { Option } from '@/lib/types';

export function IssuePicker({ options, value, onChange }: {
  options: Option[];
  value: string | null;
  onChange: (value: string) => void;
}) {
  return (
    <View style={{ gap: 6 }} accessibilityRole="radiogroup" accessibilityLabel="What was actually wrong?">
      <Body style={{ fontWeight: '700' }}>What was actually wrong?</Body>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 6 }}>
        {options.map((o) => {
          const selected = o.value === value;
          return (
            <Pressable key={o.value} accessibilityRole="radio" accessibilityState={{ checked: selected }}
              onPress={() => onChange(o.value)}
              style={{ paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999, borderWidth: 1.5,
                borderColor: selected ? colors.primary : colors.line,
                backgroundColor: selected ? colors.primarySoft : colors.surface }}>
              <Text style={{ color: selected ? colors.primary : colors.ink, fontWeight: selected ? '700' : '500' }}>
                {o.label}
              </Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

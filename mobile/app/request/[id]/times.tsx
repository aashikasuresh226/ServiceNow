/** When can a technician come? The homeowner picks a day and enters the times they're home. */
import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useMemo, useState } from 'react';
import { Pressable, ScrollView, Text, View } from 'react-native';

import { Icon } from '@/components/icons';
import { colors } from '@/components/theme';
import { TimeField } from '@/components/TimeField';
import { Button, ErrorText, Loading, Muted, Screen, StepHeader, TextLink, Title } from '@/components/ui';
import { api } from '@/lib/api';
import { useAction } from '@/lib/hooks';
import {
  type DayRanges, type LocalRange, dayKey, describeDay, fromApi, nextDays, rangeProblem, suggestRange, toApi,
} from '@/lib/homeTimes';

const DAYS_AHEAD = 7;

export default function HomeTimes() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const days = useMemo(() => nextDays(DAYS_AHEAD), []);
  const today = dayKey(days[0] ?? new Date());
  const [selected, setSelected] = useState(today);
  const [ranges, setRanges] = useState<DayRanges | null>(null);

  useEffect(() => {
    void api.getRequest(id).then((r) => {
      const saved = fromApi(r.availability);
      setRanges(Object.keys(saved).length ? saved : { [today]: [suggestRange(today)] });
    }).catch(() => setRanges({ [today]: [suggestRange(today)] }));
  }, [id, today]);

  const save = useAction(async (anyTime: boolean) => {
    if (!anyTime) {
      const all = Object.entries(ranges ?? {}).flatMap(([d, rs]) => rs.map((r) => [d, r] as const));
      if (!all.length) throw new Error('Add at least one time, or choose "Any time works"');
      const bad = all.find(([d, r]) => rangeProblem(d, r));
      if (bad) {
        setSelected(bad[0]);
        throw new Error(rangeProblem(bad[0], bad[1])!);
      }
    }
    await api.setAvailability(id, anyTime ? [] : toApi(ranges ?? {}));
    router.push(`/request/${id}/preferences`);
  });

  if (!ranges) return <Loading />;
  const forDay = ranges[selected] ?? [];
  const setDay = (next: LocalRange[]) => {
    save.setError(null);
    setRanges((prev) => {
      const copy = { ...prev };
      if (next.length) copy[selected] = next;
      else delete copy[selected];
      return copy;
    });
  };
  const summary = Object.keys(ranges).sort().map((d) => describeDay(d, ranges[d]));
  const label = new Date(`${selected}T12:00:00`).toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric' });

  return (
    <Screen footer={
      <>
        <Button label="Continue" busy={save.busy} onPress={() => save.run(false)} />
        <TextLink label="Any time works for me" color={colors.muted} onPress={() => save.run(true)} />
      </>
    }>
      <StepHeader />
      <Title sub="Add the times you'll be home. More times means a sooner visit.">When can a technician come?</Title>

      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ flexGrow: 0 }}
        contentContainerStyle={{ gap: 6, alignItems: 'flex-start' }}>
        {days.map((d) => {
          const key = dayKey(d);
          const on = key === selected;
          return (
            <Pressable key={key} accessibilityRole="button" accessibilityState={{ selected: on }}
              accessibilityLabel={d.toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })}
              onPress={() => setSelected(key)}
              style={{ width: 56, paddingVertical: 8, borderRadius: 12, alignItems: 'center', borderWidth: 1,
                borderColor: on ? colors.primary : colors.line, backgroundColor: on ? colors.primarySoft : colors.surface }}>
              <Text style={{ fontSize: 11, color: on ? colors.primaryDark : colors.muted }}>
                {key === today ? 'Today' : d.toLocaleDateString(undefined, { weekday: 'short' })}
              </Text>
              <Text style={{ fontSize: 16, fontWeight: '600', color: colors.ink }}>{d.getDate()}</Text>
              <View style={{ width: 5, height: 5, borderRadius: 3, marginTop: 2,
                backgroundColor: ranges[key]?.length ? colors.primary : 'transparent' }} />
            </Pressable>
          );
        })}
      </ScrollView>

      <View style={{ gap: 8 }}>
        <Muted>{label}</Muted>
        {forDay.map((range, i) => {
          const problem = rangeProblem(selected, range);
          const update = (patch: Partial<LocalRange>) => setDay(forDay.map((r, j) => (j === i ? { ...r, ...patch } : r)));
          return (
            <View key={i} style={{ gap: 4 }}>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
                <TimeField label="From" value={range.from} invalid={!!problem} onChange={(v) => update({ from: v })} />
                <Text style={{ color: colors.muted }}>to</Text>
                <TimeField label="To" value={range.to} invalid={!!problem} onChange={(v) => update({ to: v })} />
                <Pressable accessibilityRole="button" accessibilityLabel="Remove this time" hitSlop={10}
                  onPress={() => setDay(forDay.filter((_, j) => j !== i))}>
                  <Icon name="x" size={18} color={colors.faint} />
                </Pressable>
              </View>
              {problem ? <Text style={{ color: colors.danger, fontSize: 12 }}>{problem}</Text> : null}
            </View>
          );
        })}
        <TextLink label={forDay.length ? '+ Add another time' : '+ Add a time'}
          onPress={() => {
            const last = forDay[forDay.length - 1];
            setDay([...forDay, last && last.to < '21:00'
              ? { from: last.to, to: `${String(Math.min(Number(last.to.slice(0, 2)) + 2, 23)).padStart(2, '0')}:${last.to.slice(3)}` }
              : suggestRange(selected)]);
          }} />
      </View>

      {summary.length ? (
        <View style={{ flexDirection: 'row', gap: 10, borderTopWidth: 1, borderTopColor: colors.line, paddingTop: 12 }}>
          <Icon name="calendar" size={18} color={colors.accent} />
          <View style={{ flex: 1, gap: 2 }}>
            {summary.map((line) => <Text key={line} style={{ color: colors.body, fontSize: 13 }}>{line}</Text>)}
          </View>
        </View>
      ) : null}
      <ErrorText message={save.error} />
    </Screen>
  );
}

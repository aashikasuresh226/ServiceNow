/** Small, consistent UI primitives used by every screen. */
import { router } from 'expo-router';
import type { ReactNode } from 'react';
import {
  ActivityIndicator,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
  useWindowDimensions,
} from 'react-native';
import type { StyleProp, TextInputProps, TextProps, TextStyle, ViewStyle } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Icon } from './icons';
import type { IconName } from './icons';
import { colors, font, radius } from './theme';

/** Phone-width column. On a desktop browser it renders as a centered device frame. */
export function Screen({
  children,
  footer,
  scroll = true,
}: {
  children: ReactNode;
  footer?: ReactNode;
  scroll?: boolean;
}) {
  const { width } = useWindowDimensions();
  const framed = Platform.OS === 'web' && width >= 520;
  const body = scroll ? (
    <ScrollView
      contentContainerStyle={styles.scrollContent}
      keyboardShouldPersistTaps="handled"
      showsVerticalScrollIndicator={false}
    >
      {children}
    </ScrollView>
  ) : (
    <View style={[styles.scrollContent, { flex: 1 }]}>{children}</View>
  );
  return (
    <View style={[styles.outer, framed && styles.outerFramed]}>
      <SafeAreaView style={[styles.column, framed && styles.columnFramed]} edges={['top', 'bottom']}>
        {body}
        {footer ? <View style={styles.footer}>{footer}</View> : null}
      </SafeAreaView>
    </View>
  );
}

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'dark';

export function Button({
  label,
  onPress,
  variant = 'primary',
  busy = false,
  disabled = false,
  icon,
  style,
  accessibilityLabel,
}: {
  label: string;
  onPress: () => void;
  variant?: ButtonVariant;
  busy?: boolean;
  disabled?: boolean;
  icon?: IconName;
  style?: StyleProp<ViewStyle>;
  accessibilityLabel?: string;
}) {
  const v = buttonVariants[variant];
  const inactive = disabled || busy;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel ?? label}
      accessibilityState={{ disabled: inactive, busy }}
      disabled={inactive}
      onPress={onPress}
      style={({ pressed }) => [
        styles.button,
        { backgroundColor: v.bg, borderColor: v.border },
        pressed && !inactive && { opacity: 0.85 },
        inactive && { opacity: 0.55 },
        style,
      ]}
    >
      {busy ? (
        <ActivityIndicator color={v.fg} />
      ) : (
        <View style={styles.buttonInner}>
          {icon ? <Icon name={icon} size={18} color={v.fg} /> : null}
          <Text style={[styles.buttonText, { color: v.fg }]}>{label}</Text>
        </View>
      )}
    </Pressable>
  );
}

const buttonVariants: Record<ButtonVariant, { bg: string; fg: string; border: string }> = {
  primary: { bg: colors.primary, fg: '#FFFFFF', border: colors.primary },
  secondary: { bg: colors.surface, fg: colors.ink, border: colors.lineStrong },
  ghost: { bg: 'transparent', fg: colors.primary, border: 'transparent' },
  danger: { bg: colors.surface, fg: colors.danger, border: colors.lineStrong },
  dark: { bg: colors.ink, fg: '#FFFFFF', border: colors.ink },
};

export function TextLink({ label, onPress, color = colors.primary }: {
  label: string;
  onPress: () => void;
  color?: string;
}) {
  return (
    <Pressable accessibilityRole="link" onPress={onPress} hitSlop={10} style={styles.link}>
      <Text style={[styles.linkText, { color }]}>{label}</Text>
    </Pressable>
  );
}

export function Card({ children, style, tone = 'plain' }: {
  children: ReactNode;
  style?: StyleProp<ViewStyle>;
  tone?: 'plain' | 'soft' | 'muted' | 'amber';
}) {
  const toneStyle = {
    plain: { backgroundColor: colors.surface, borderColor: colors.line, borderWidth: 1 },
    soft: { backgroundColor: colors.primarySoft },
    muted: { backgroundColor: colors.background },
    amber: { backgroundColor: colors.amberSoft },
  }[tone];
  return <View style={[styles.card, toneStyle, style]}>{children}</View>;
}

export function Title({ children, sub }: { children: ReactNode; sub?: string }) {
  return (
    <View style={{ gap: 4 }}>
      <Text style={styles.title} accessibilityRole="header">
        {children}
      </Text>
      {sub ? <Text style={styles.sub}>{sub}</Text> : null}
    </View>
  );
}

export function Label({ children, style }: { children: ReactNode; style?: StyleProp<TextStyle> }) {
  return <Text style={[styles.label, style]}>{children}</Text>;
}

export function Body({ style, ...props }: TextProps) {
  return <Text {...props} style={[styles.body, style]} />;
}

export function Muted({ style, ...props }: TextProps) {
  return <Text {...props} style={[styles.muted, style]} />;
}

/** Back button + "Step n of 4" + progress bar. */
export function StepHeader({ step, total = 4, onBack }: {
  step?: number;
  total?: number;
  onBack?: () => void;
}) {
  const back = onBack ?? (() => (router.canGoBack() ? router.back() : router.replace('/home')));
  return (
    <View style={{ gap: 10 }}>
      <View style={styles.row}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Back"
          onPress={back}
          hitSlop={12}
          style={styles.backButton}
        >
          <Icon name="chevronLeft" size={22} color={colors.ink} />
        </Pressable>
        {step ? <Muted>Step {step} of {total}</Muted> : null}
      </View>
      {step ? (
        <View style={styles.progressRow} accessibilityLabel={`Step ${step} of ${total}`}>
          {Array.from({ length: total }, (_, i) => (
            <View
              key={i}
              style={[styles.progress, { backgroundColor: i < step ? colors.primary : colors.line }]}
            />
          ))}
        </View>
      ) : null}
    </View>
  );
}

/** Square selectable tile with an icon (symptoms, soft skills). */
export function Tile({ label, icon, selected, onPress }: {
  label: string;
  icon: IconName;
  selected: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityRole="checkbox"
      accessibilityState={{ checked: selected }}
      accessibilityLabel={label}
      onPress={onPress}
      style={[styles.tile, selected && styles.tileSelected]}
    >
      <Icon name={icon} size={24} color={selected ? '#FFFFFF' : colors.ink} />
      <Text style={[styles.tileText, selected && { color: '#FFFFFF' }]} numberOfLines={2}>
        {label}
      </Text>
    </Pressable>
  );
}

export function Segmented({ options, value, onChange }: {
  options: { value: string; label: string }[];
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <View style={styles.segmented} accessibilityRole="radiogroup">
      {options.map((o, i) => {
        const active = o.value === value;
        return (
          <Pressable
            key={o.value}
            accessibilityRole="radio"
            accessibilityState={{ checked: active }}
            onPress={() => onChange(o.value)}
            style={[
              styles.segment,
              i > 0 && { borderLeftWidth: 1, borderLeftColor: colors.lineStrong },
              active && { backgroundColor: colors.ink },
            ]}
          >
            <Text style={[styles.segmentText, active && { color: '#FFFFFF', fontWeight: '700' }]}>
              {o.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

export function Field({ label, error, ...props }: TextInputProps & { label: string; error?: string }) {
  return (
    <View style={{ gap: 6 }}>
      <Text style={styles.fieldLabel}>{label}</Text>
      <TextInput
        accessibilityLabel={label}
        placeholderTextColor={colors.faint}
        {...props}
        style={[styles.input, props.multiline && styles.inputMultiline, props.style]}
      />
      {error ? <ErrorText message={error} /> : null}
    </View>
  );
}

export function Checkbox({ label, checked, onChange, hint }: {
  label: string;
  checked: boolean;
  onChange: (value: boolean) => void;
  hint?: string;
}) {
  return (
    <Pressable
      accessibilityRole="checkbox"
      accessibilityState={{ checked }}
      onPress={() => onChange(!checked)}
      style={styles.checkRow}
    >
      <View style={[styles.checkbox, checked && styles.checkboxOn]}>
        {checked ? <Icon name="check" size={14} color="#FFFFFF" strokeWidth={3} /> : null}
      </View>
      <View style={{ flex: 1 }}>
        <Body>{label}</Body>
        {hint ? <Muted>{hint}</Muted> : null}
      </View>
    </Pressable>
  );
}

export function ErrorText({ message }: { message: string | null | undefined }) {
  if (!message) return null;
  return (
    <View style={styles.error} accessibilityRole="alert">
      <Icon name="alert" size={16} color={colors.danger} />
      <Text style={styles.errorText}>{message}</Text>
    </View>
  );
}

export function Badge({ label, tone = 'primary' }: {
  label: string;
  tone?: 'primary' | 'amber' | 'neutral' | 'success';
}) {
  const t = {
    primary: { bg: colors.primarySoft, fg: colors.primary },
    amber: { bg: colors.amberSoft, fg: colors.amberInk },
    neutral: { bg: '#E9ECF0', fg: colors.body },
    success: { bg: colors.successSoft, fg: colors.success },
  }[tone];
  return (
    <View style={[styles.badge, { backgroundColor: t.bg }]}>
      <Text style={[styles.badgeText, { color: t.fg }]}>{label}</Text>
    </View>
  );
}

export function Row({ children, style }: { children: ReactNode; style?: StyleProp<ViewStyle> }) {
  return <View style={[styles.row, style]}>{children}</View>;
}

export function KeyValue({ k, v }: { k: string; v: string }) {
  return (
    <Row style={{ justifyContent: 'space-between' }}>
      <Muted>{k}</Muted>
      <Body style={{ fontWeight: '600' }}>{v}</Body>
    </Row>
  );
}

export function Loading({ label }: { label?: string }) {
  return (
    <View style={styles.loading}>
      <ActivityIndicator color={colors.primary} size="large" />
      {label ? <Muted>{label}</Muted> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  outer: { flex: 1, backgroundColor: colors.background },
  outerFramed: { backgroundColor: colors.frame, alignItems: 'center', paddingVertical: 24 },
  column: { flex: 1, width: '100%', backgroundColor: colors.background },
  columnFramed: {
    maxWidth: 420,
    borderRadius: 28,
    overflow: 'hidden',
    borderWidth: 1,
    borderColor: colors.lineStrong,
    boxShadow: '0 20px 50px rgba(26, 31, 43, 0.18)',
  },
  scrollContent: { padding: 20, gap: 16, flexGrow: 1 },
  footer: {
    paddingHorizontal: 20,
    paddingTop: 12,
    paddingBottom: 16,
    gap: 10,
    borderTopWidth: 1,
    borderTopColor: colors.line,
    backgroundColor: colors.background,
  },
  button: {
    minHeight: 48,
    borderRadius: radius.md,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 16,
  },
  buttonInner: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  buttonText: { fontSize: font.size.md + 1, fontWeight: '600' },
  link: { alignSelf: 'center', paddingVertical: 6, minHeight: 32, justifyContent: 'center' },
  linkText: { fontSize: font.size.md, fontWeight: '600' },
  card: { borderRadius: radius.lg, padding: 14, gap: 10 },
  title: { fontSize: font.size.xxl, fontWeight: '700', color: colors.ink, letterSpacing: -0.3 },
  sub: { fontSize: font.size.md, color: colors.muted, lineHeight: 20 },
  label: {
    fontSize: font.size.xs,
    fontWeight: '700',
    color: colors.muted,
    textTransform: 'uppercase',
    letterSpacing: 0.8,
  },
  body: { fontSize: font.size.md, color: colors.ink, lineHeight: 20 },
  muted: { fontSize: font.size.sm + 1, color: colors.muted, lineHeight: 18 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  backButton: { width: 32, height: 32, alignItems: 'center', justifyContent: 'center', marginLeft: -6 },
  progressRow: { flexDirection: 'row', gap: 4 },
  progress: { flex: 1, height: 4, borderRadius: 2 },
  tile: {
    flexBasis: '30%',
    flexGrow: 1,
    minHeight: 84,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: colors.surface,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    padding: 8,
  },
  tileSelected: { backgroundColor: colors.primary, borderColor: colors.primary },
  tileText: { fontSize: font.size.sm, fontWeight: '600', color: colors.ink, textAlign: 'center' },
  segmented: {
    flexDirection: 'row',
    borderWidth: 1,
    borderColor: colors.lineStrong,
    borderRadius: 10,
    overflow: 'hidden',
    backgroundColor: colors.surface,
  },
  segment: { flex: 1, minHeight: 40, alignItems: 'center', justifyContent: 'center' },
  segmentText: { fontSize: font.size.sm + 1, color: colors.ink },
  fieldLabel: { fontSize: font.size.sm + 1, fontWeight: '600', color: colors.ink },
  input: {
    minHeight: 46,
    borderWidth: 1,
    borderColor: colors.lineStrong,
    borderRadius: radius.md,
    paddingHorizontal: 12,
    fontSize: font.size.lg,
    color: colors.ink,
    backgroundColor: colors.surface,
  },
  inputMultiline: { minHeight: 88, paddingTop: 10, textAlignVertical: 'top' },
  checkRow: { flexDirection: 'row', gap: 10, alignItems: 'flex-start', paddingVertical: 4 },
  checkbox: {
    width: 22,
    height: 22,
    borderRadius: 6,
    borderWidth: 1.5,
    borderColor: colors.lineStrong,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.surface,
    marginTop: 1,
  },
  checkboxOn: { backgroundColor: colors.primary, borderColor: colors.primary },
  error: {
    flexDirection: 'row',
    gap: 8,
    alignItems: 'center',
    backgroundColor: colors.dangerSoft,
    borderRadius: radius.sm,
    padding: 10,
  },
  errorText: { color: colors.danger, fontSize: font.size.sm + 1, flex: 1 },
  badge: { alignSelf: 'flex-start', borderRadius: 999, paddingHorizontal: 10, paddingVertical: 3 },
  badgeText: { fontSize: font.size.xs, fontWeight: '700', letterSpacing: 0.3 },
  loading: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 12, padding: 40 },
});

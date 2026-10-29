/** Simple vector illustrations (from the wireflow). No image assets or map API keys needed. */
import { Platform } from 'react-native';
import Svg, { Circle, G, Path, Rect, Text as SvgText } from 'react-native-svg';

import { colors } from './theme';
import { decorative } from '@/components/a11y';

/** SVG text falls back to a serif font in browsers unless told otherwise. */
const SVG_FONT = Platform.OS === 'web' ? 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif' : undefined;

export function HouseIllustration({ width = 240 }: { width?: number }) {
  return (
    <Svg width={width} height={width * (100 / 240)} viewBox="0 0 240 100" {...decorative}>
      <Path d="M10 94H230" stroke={colors.faint} strokeWidth={2} strokeLinecap="round" />
      <Rect x={58} y={44} width={92} height={50} fill="#FFFFFF" stroke={colors.ink} strokeWidth={2} />
      <Path d="M48 46L104 12L160 46Z" fill={colors.primary} stroke={colors.ink} strokeWidth={2} strokeLinejoin="round" />
      <Rect x={94} y={64} width={20} height={30} fill={colors.primaryTint} stroke={colors.ink} strokeWidth={2} />
      <Rect x={68} y={56} width={18} height={14} fill={colors.primaryTint} stroke={colors.ink} strokeWidth={2} />
      <Rect x={122} y={56} width={18} height={14} fill={colors.primaryTint} stroke={colors.ink} strokeWidth={2} />
      <Rect x={164} y={68} width={32} height={26} rx={3} fill="#EEF0F3" stroke={colors.ink} strokeWidth={2} />
      <Circle cx={180} cy={81} r={8} fill="#FFFFFF" stroke={colors.muted} strokeWidth={2} />
      <Path d="M200 66c4-4 4-8 0-12M208 70c7-7 7-15 0-22" fill="none" stroke={colors.primary} strokeWidth={2} strokeLinecap="round" />
      <Circle cx={206} cy={24} r={14} fill="#FFFFFF" stroke={colors.primary} strokeWidth={2} />
      <Path d="M209 18a4 4 0 0 0-5 5l-6 6 2 2 6-6a4 4 0 0 0 5-5l-2.5 2.5-2-2z" fill={colors.primary} />
    </Svg>
  );
}

export function AcUnit({ width = 110, dark = false, highlightLabel = false }: {
  width?: number;
  dark?: boolean;
  highlightLabel?: boolean;
}) {
  const body = dark ? '#3A4152' : '#FFFFFF';
  const stroke = dark ? colors.faint : colors.muted;
  const label = highlightLabel ? colors.primaryTint : dark ? '#D6DAE1' : '#FFFFFF';
  return (
    <Svg width={width} height={width * (100 / 120)} viewBox="0 0 120 100" {...decorative}>
      <Rect x={12} y={10} width={96} height={76} rx={6} fill={body} stroke={stroke} strokeWidth={2} />
      <Circle cx={54} cy={52} r={24} fill={dark ? '#2B3140' : '#FFFFFF'} stroke={stroke} strokeWidth={2} />
      <Path d="M54 52c0-10 6-14 10-12M54 52c9 3 11 10 8 13M54 52c-8 6-15 4-16 0" fill="none" stroke={stroke} strokeWidth={3} strokeLinecap="round" />
      <Circle cx={54} cy={52} r={3.5} fill={stroke} />
      <Rect x={88} y={28} width={14} height={22} rx={2} fill={label} stroke={highlightLabel ? colors.primary : stroke} strokeWidth={2} />
      <Rect x={20} y={86} width={14} height={6} fill={stroke} />
      <Rect x={86} y={86} width={14} height={6} fill={stroke} />
    </Svg>
  );
}

/** Camera viewfinder framing the unit and its data plate. */
export function Viewfinder({ width = 220 }: { width?: number }) {
  return (
    <Svg width={width} height={width * (190 / 220)} viewBox="0 0 220 190" {...decorative}>
      <Path d="M14 30V14h16M190 14h16v16M206 160v16h-16M30 176H14v-16" fill="none" stroke="#FFFFFF" strokeWidth={2.5} strokeLinecap="round" />
      <G transform="translate(40 40) scale(1.15)">
        <Rect x={12} y={10} width={96} height={76} rx={6} fill="#3A4152" stroke={colors.faint} strokeWidth={2} />
        <Circle cx={54} cy={52} r={24} fill="#2B3140" stroke={colors.faint} strokeWidth={2} />
        <Rect x={88} y={28} width={14} height={22} rx={2} fill="#D6DAE1" />
      </G>
      <Rect x={134} y={62} width={34} height={42} rx={4} fill="none" stroke="#7FA0F5" strokeWidth={2.5} />
      <Rect x={124} y={40} width={54} height={16} rx={8} fill={colors.primary} />
      <SvgText fontFamily={SVG_FONT} x={151} y={51.5} textAnchor="middle" fontSize={10} fontWeight="600" fill="#FFFFFF">
        Data plate
      </SvgText>
    </Svg>
  );
}

export function Avatar({ size = 48, name }: { size?: number; name?: string }) {
  // Deterministic skin tone per name, so the same tech always looks the same.
  const tones = ['#E2B48C', '#C68B59', '#8D5524', '#F1C27D', '#D9A066'];
  const tone = tones[(name ?? '').length % tones.length];
  return (
    <Svg width={size} height={size} viewBox="0 0 48 48" accessibilityLabel={name ? `${name}'s photo` : undefined}>
      <Rect width={48} height={48} rx={24} fill={colors.primaryTint} />
      <Path d="M7 48c1-12 33-12 34 0z" fill={colors.primary} />
      <Circle cx={24} cy={21} r={8.5} fill={tone} />
      <Path d="M15 19a9 9 0 0 1 18 0z" fill={colors.ink} />
      <Rect x={13} y={18} width={22} height={3} rx={1.5} fill={colors.ink} />
    </Svg>
  );
}

/** Stylized street map with a route from the technician to the home. */
export function RouteMap({ height = 170, progress = 0, label }: {
  height?: number;
  progress?: number; // 0 = at the shop, 1 = arrived
  label?: string;
}) {
  // Route: shop (40,140) → (40,80) → (250,80) → (250,40) home
  const pts: [number, number][] = [[40, 140], [40, 80], [250, 80], [250, 44]];
  const segs = pts.slice(1).map((p, i) => Math.hypot(p[0] - pts[i]![0], p[1] - pts[i]![1]));
  const total = segs.reduce((a, b) => a + b, 0);
  let remaining = Math.min(1, Math.max(0, progress)) * total;
  let truck: [number, number] = pts[0]!;
  for (let i = 0; i < segs.length; i++) {
    const seg = segs[i]!;
    const a = pts[i]!;
    const b = pts[i + 1]!;
    if (remaining <= seg) {
      const t = seg ? remaining / seg : 0;
      truck = [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
      break;
    }
    remaining -= seg;
    truck = b;
  }
  return (
    <Svg width="100%" height={height} viewBox="0 0 300 170" preserveAspectRatio="xMidYMid slice" accessibilityLabel={label ?? 'Map showing the technician route'}>
      <Rect width={300} height={170} fill="#E9ECF0" />
      <Rect x={180} y={10} width={100} height={50} rx={6} fill="#DCE8DA" />
      <Rect x={10} y={10} width={20} height={56} rx={4} fill="#DDE1E7" />
      <Rect x={60} y={100} width={160} height={60} rx={4} fill="#DDE1E7" />
      <Path d="M0 80H300M40 0V170M250 0V170M150 80V170" stroke="#FFFFFF" strokeWidth={12} />
      <Path d="M40 140V80H250V44" fill="none" stroke={colors.primary} strokeWidth={4} strokeLinecap="round" strokeLinejoin="round" />
      <Path d="M250 50s-10-9-10-17a10 10 0 0 1 20 0c0 8-10 17-10 17z" fill={colors.ink} />
      <Circle cx={250} cy={33} r={3.5} fill="#FFFFFF" />
      <Circle cx={truck[0]} cy={truck[1]} r={11} fill={colors.primary} stroke="#FFFFFF" strokeWidth={3} />
      <Path d={`M${truck[0] - 5} ${truck[1] + 1}h6v-3h3l2 3v2h-11z`} fill="#FFFFFF" />
    </Svg>
  );
}

/** Circular countdown/progress ring with a big number in the middle. */
export function Ring({ size = 150, fraction, big, small, color = colors.amber, track = '#F0E2D2' }: {
  size?: number;
  fraction: number;
  big: string;
  small: string;
  color?: string;
  track?: string;
}) {
  const r = 58;
  const circumference = 2 * Math.PI * r;
  const filled = Math.min(1, Math.max(0.02, fraction)) * circumference;
  return (
    <Svg width={size} height={size} viewBox="0 0 140 140" accessibilityLabel={`${big} ${small}`}>
      <Circle cx={70} cy={70} r={r} fill="none" stroke={track} strokeWidth={12} />
      <Circle cx={70} cy={70} r={r} fill="none" stroke={color} strokeWidth={12} strokeLinecap="round" strokeDasharray={`${filled} ${circumference}`} transform="rotate(-90 70 70)" />
      <SvgText fontFamily={SVG_FONT} x={70} y={74} textAnchor="middle" fontSize={28} fontWeight="700" fill={colors.ink}>
        {big}
      </SvgText>
      <SvgText fontFamily={SVG_FONT} x={70} y={95} textAnchor="middle" fontSize={11} fill={colors.muted}>
        {small}
      </SvgText>
    </Svg>
  );
}

/** Price range bar: the solid part is the estimate, hatched part is "final price on site". */
export function EstimateBar() {
  return (
    <Svg width="100%" height={10} viewBox="0 0 200 10" preserveAspectRatio="none" {...decorative}>
      <Rect width={200} height={10} rx={5} fill={colors.primarySoft} />
      {Array.from({ length: 30 }, (_, i) => (
        <Path key={i} d={`M${55 + i * 6} 10L${61 + i * 6} 0`} stroke={colors.primaryTint} strokeWidth={3} />
      ))}
      <Rect width={50} height={10} rx={5} fill={colors.primary} />
    </Svg>
  );
}

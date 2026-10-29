/** Stroke icons (24x24 grid), drawn with react-native-svg so they work on web and native. */
import Svg, { Circle, Path, Rect } from 'react-native-svg';
import { decorative } from '@/components/a11y';

const PATHS = {
  chevronLeft: ['M15 18l-6-6 6-6'],
  chevronRight: ['M9 6l6 6-6 6'],
  check: ['M5 12l5 5 9-10'],
  x: ['M6 6l12 12M18 6L6 18'],
  alert: ['M12 8v5M12 16.5v.01', 'M10.3 3.9L2.4 17.5A2 2 0 0 0 4.1 20.5h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z'],
  info: ['M12 11v5M12 8v.01'],
  snowflake: ['M12 2v20M3.5 7l17 10M20.5 7l-17 10M9 4l3 2 3-2M9 20l3-2 3 2'],
  flame: ['M12 3c3 4 6 6 6 11a6 6 0 0 1-12 0c0-3 2-5 3-7 1 2 2 3 3 3 0-3-1-5 0-7z'],
  volume: ['M4 10v4h4l5 4V6L8 10zM16 9a4 4 0 0 1 0 6M19 6a8 8 0 0 1 0 12'],
  drop: ['M12 3s6 7 6 11a6 6 0 0 1-12 0c0-4 6-11 6-11z'],
  power: ['M12 3v9M6.5 7a8 8 0 1 0 11 0'],
  wind: ['M3 9h11a3 3 0 1 0-3-3M3 15h15a3 3 0 1 1-3 3'],
  camera: ['M4 8h3l2-3h6l2 3h3v11H4z'],
  image: ['M21 16l-5-5-9 9'],
  flash: ['M13 2L5 14h6l-1 8 8-12h-6z'],
  wrench: ['M14.7 6.3a4 4 0 0 0-5.4 5.4L4 17l3 3 5.3-5.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.5-2.5z'],
  home: ['M4 11l8-7 8 7v9H4z'],
  list: ['M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01'],
  user: ['M4 21c1-5 15-5 16 0'],
  sparkle: ['M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z'],
  chat: ['M4 5h16v11H9l-5 4z', 'M8 9h8M8 12h5'],
  clock: ['M12 7v5l3 2'],
  heart: ['M12 20s-7-4.5-7-10a4 4 0 0 1 7-2.5A4 4 0 0 1 19 10c0 5.5-7 10-7 10z'],
  globe: ['M3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18'],
  phone: ['M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2z'],
  shield: ['M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z'],
  tag: ['M3 12V4h8l10 10-8 8z'],
  calendar: ['M4 10h16M8 3v4M16 3v4'],
  mapPin: ['M12 21s-7-6.5-7-12a7 7 0 0 1 14 0c0 5.5-7 12-7 12z'],
  truck: ['M3 7h11v9H3zM14 10h4l3 3v3h-7'],
  star: ['M12 3l2.6 5.6 6.1.7-4.5 4.2 1.2 6L12 16.6 6.6 19.5l1.2-6L3.3 9.3l6.1-.7z'],
  lock: ['M8 11V8a4 4 0 0 1 8 0v3'],
  card: ['M3 10h18'],
  building: ['M4 21V5l8-2v18M12 9h8v12M4 21h16'],
  refresh: ['M4 12a8 8 0 0 1 14-5.3L20 9M20 4v5h-5M20 12a8 8 0 0 1-14 5.3L4 15M4 20v-5h5'],
  mic: ['M5 11a7 7 0 0 0 14 0M12 18v3'],
  logout: ['M15 4h4v16h-4M10 8l-4 4 4 4M6 12h11'],
  plus: ['M12 5v14M5 12h14'],
} as const;

export type IconName = keyof typeof PATHS;

/** Extra shapes some icons need beyond paths. */
function extras(name: IconName, color: string) {
  switch (name) {
    case 'info':
    case 'clock':
    case 'globe':
      return <Circle cx={12} cy={12} r={9} stroke={color} />;
    case 'camera':
      return <Circle cx={12} cy={13} r={3.5} stroke={color} />;
    case 'image':
      return (
        <>
          <Rect x={3} y={4} width={18} height={16} rx={2} stroke={color} />
          <Circle cx={9} cy={10} r={2} stroke={color} />
        </>
      );
    case 'user':
      return <Circle cx={12} cy={8} r={4} stroke={color} />;
    case 'calendar':
      return <Rect x={4} y={5} width={16} height={15} rx={2} stroke={color} />;
    case 'mapPin':
      return <Circle cx={12} cy={9} r={2.5} stroke={color} />;
    case 'truck':
      return (
        <>
          <Circle cx={7} cy={17} r={2} stroke={color} />
          <Circle cx={17} cy={17} r={2} stroke={color} />
        </>
      );
    case 'lock':
      return <Rect x={5} y={11} width={14} height={10} rx={2} stroke={color} />;
    case 'card':
      return <Rect x={3} y={5} width={18} height={14} rx={2} stroke={color} />;
    case 'tag':
      return <Circle cx={7.5} cy={7.5} r={1.5} stroke={color} />;
    case 'mic':
      return <Rect x={9} y={3} width={6} height={11} rx={3} stroke={color} />;
    default:
      return null;
  }
}

export function Icon({ name, size = 20, color = '#1A1F2B', strokeWidth = 2 }: {
  name: IconName;
  size?: number;
  color?: string;
  strokeWidth?: number;
}) {
  return (
    <Svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      {...decorative}
    >
      {extras(name, color)}
      {PATHS[name].map((d) => (
        <Path key={d} d={d} stroke={color} />
      ))}
    </Svg>
  );
}

/** Which icon represents each option value coming from the API. */
export const OPTION_ICONS: Record<string, IconName> = {
  no_cooling: 'snowflake',
  no_heat: 'flame',
  noisy: 'volume',
  leaking: 'drop',
  wont_start: 'power',
  odd_smell: 'wind',
  explains_clearly: 'chat',
  punctual: 'clock',
  patient: 'heart',
  tidy: 'sparkle',
  spanish_speaking: 'globe',
  shows_work: 'camera',
};

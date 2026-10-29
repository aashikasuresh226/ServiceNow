const PATHS: Record<string, string[]> = {
  dashboard: ['M4 13h6V4H4zM14 20h6v-9h-6zM4 20h6v-3H4zM14 7h6V4h-6z'],
  jobs: ['M9 6V4h6v2M4 7h16v12H4zM4 12h16'],
  users: ['M2 20c1-5 11-5 12 0M16 4.5a3.5 3.5 0 0 1 0 7M18 14c2 .6 3.5 2.6 4 6'],
  calendar: ['M4 10h16M8 3v4M16 3v4'],
  plug: ['M9 3v5M15 3v5M6 8h12v4a6 6 0 0 1-12 0zM12 18v3'],
  settings: ['M12 3l1.6 2.5 2.9-.6.6 2.9L19.6 9.5 18 12l1.6 2.5-2.5 1.7-.6 2.9-2.9-.6L12 21l-1.6-2.5-2.9.6-.6-2.9L4.4 14.5 6 12 4.4 9.5l2.5-1.7.6-2.9 2.9.6z'],
  wallet: ['M3 7h18v12H3zM3 7l3-3h12l3 3M16 13h2'],
  logout: ['M15 4h4v16h-4M10 8l-4 4 4 4M6 12h11'],
  wrench: ['M14.7 6.3a4 4 0 0 0-5.4 5.4L4 17l3 3 5.3-5.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.5-2.5z'],
  user: ['M4 21c1-5 15-5 16 0'],
  clock: ['M12 7v5l3 2'],
  check: ['M5 12l5 5 9-10'],
  x: ['M6 6l12 12M18 6L6 18'],
  alert: ['M12 8v5M12 16.5v.01', 'M10.3 3.9L2.4 17.5A2 2 0 0 0 4.1 20.5h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z'],
  shield: ['M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z'],
  sparkle: ['M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z'],
  refresh: ['M4 12a8 8 0 0 1 14-5.3L20 9M20 4v5h-5M20 12a8 8 0 0 1-14 5.3L4 15M4 20v-5h5'],
  truck: ['M3 7h11v9H3zM14 10h4l3 3v3h-7'],
  plus: ['M12 5v14M5 12h14'],
  mapPin: ['M12 21s-7-6.5-7-12a7 7 0 0 1 14 0c0 5.5-7 12-7 12z'],
  phone: ['M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2z'],
  bank: ['M3 9l9-6 9 6zM5 20h14M6 10v8M10 10v8M14 10v8M18 10v8'],
};

const CIRCLES: Record<string, [number, number, number][]> = {
  users: [[8, 8, 4]],
  user: [[12, 8, 4]],
  clock: [[12, 12, 9]],
  settings: [[12, 12, 3]],
  mapPin: [[12, 9, 2.5]],
  truck: [[7, 17, 2], [17, 17, 2]],
};

export function Icon({ name, size = 18, color = 'currentColor', label }: {
  name: keyof typeof PATHS | string;
  size?: number;
  color?: string;
  label?: string;
}) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2}
      strokeLinecap="round" strokeLinejoin="round" role={label ? 'img' : undefined}
      aria-label={label} aria-hidden={label ? undefined : true}>
      {name === 'calendar' ? <rect x="4" y="5" width="16" height="15" rx="2" /> : null}
      {(CIRCLES[name] ?? []).map(([cx, cy, r]) => <circle key={`${cx}${cy}`} cx={cx} cy={cy} r={r} />)}
      {(PATHS[name] ?? []).map((d) => <path key={d} d={d} />)}
    </svg>
  );
}

export function Avatar({ name, size = 36 }: { name: string; size?: number }) {
  const tones = ['#E2B48C', '#C68B59', '#8D5524', '#F1C27D', '#D9A066'];
  const tone = tones[name.length % tones.length];
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" role="img" aria-label={`${name}'s photo`}>
      <rect width="48" height="48" rx="24" fill="#DCE5FB" />
      <path d="M7 48c1-12 33-12 34 0z" fill="#1D4ED8" />
      <circle cx="24" cy="21" r="8.5" fill={tone} />
      <path d="M15 19a9 9 0 0 1 18 0z" fill="#1A1F2B" />
      <rect x="13" y="18" width="22" height="3" rx="1.5" fill="#1A1F2B" />
    </svg>
  );
}

/** Design tokens (match the wireflow). */
export const colors = {
  primary: '#1D4ED8',
  primaryDark: '#1E3A8A',
  primarySoft: '#E8EEFD',
  primaryTint: '#DCE5FB',
  ink: '#1A1F2B',
  body: '#3E4654',
  muted: '#5B6372',
  faint: '#9AA3B2',
  line: '#DDE1E7',
  lineStrong: '#C9CED6',
  surface: '#FFFFFF',
  background: '#F4F5F7',
  frame: '#E3E6EB',
  amber: '#B45309',
  amberInk: '#8A3F06',
  amberSoft: '#FDF1E3',
  danger: '#B42318',
  dangerSoft: '#FEECEB',
  success: '#0F7B4B',
  successSoft: '#E6F4EC',
} as const;

export const radius = { sm: 8, md: 12, lg: 16, xl: 24 } as const;

export const font = {
  family: undefined as string | undefined, // platform default (San Francisco / Roboto / Segoe UI)
  size: { xs: 11, sm: 12, md: 14, lg: 16, xl: 20, xxl: 26, hero: 40 },
} as const;

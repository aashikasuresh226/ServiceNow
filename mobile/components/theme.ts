/** Brand tokens: "Indigo and teal". Confident indigo for actions and the logo, a calm teal
 * accent used sparingly, near-black navy text on white and cool light gray. */
export const colors = {
  primary: '#4F52D9', // indigo: buttons, links, selection, logo (white text passes AA)
  primaryDark: '#3237A8', // pressed, and indigo text on light tints
  primarySoft: '#EEF0FE',
  primaryTint: '#DCDFFC',
  accent: '#12A594', // teal: positive status, highlights (sparingly)
  accentSoft: '#E3F6F3',
  accentInk: '#0B6B60', // teal text on accentSoft
  logoAir: '#7FE0D2', // inner air stream of the logo
  ink: '#1B2140',
  body: '#3F4663',
  muted: '#5F6680',
  faint: '#9CA3B4',
  line: '#E5E7EB',
  lineStrong: '#D1D5DE',
  surface: '#FFFFFF',
  background: '#F7F8FB',
  frame: '#E9EBF2',
  amber: '#B45309',
  amberInk: '#8A3F06',
  amberSoft: '#FDF1E3',
  danger: '#B42318',
  dangerSoft: '#FEECEB',
  success: '#0B6B60',
  successSoft: '#E3F6F3',
} as const;

export const radius = { sm: 8, md: 12, lg: 16, xl: 24 } as const;

export const font = {
  family: undefined as string | undefined, // platform default (San Francisco / Roboto / Segoe UI)
  size: { xs: 11, sm: 12, md: 14, lg: 16, xl: 20, xxl: 26, hero: 40 },
} as const;

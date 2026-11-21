/** Brand tokens: "Petrol and sand" (deep petrol green-teal on warm sand). */
export const colors = {
  primary: '#2F7A70', // petrol: buttons, links, selection (white text passes AA)
  primaryDark: '#15403B', // deep petrol: headers, logo, pressed
  primarySoft: '#E4F0ED',
  primaryTint: '#CFE5E0',
  sand: '#E3D5B8', // brand accent: logo lines, highlights
  sandSoft: '#F1E9D8',
  sandInk: '#4D3D18', // text on sand
  ink: '#1C2B29',
  body: '#3B4A47',
  muted: '#5C6964',
  faint: '#9AA39E',
  line: '#E5DFD2',
  lineStrong: '#D3CBBA',
  surface: '#FFFFFF',
  background: '#F6F2EA',
  frame: '#E7E1D4',
  amber: '#B45309',
  amberInk: '#8A3F06',
  amberSoft: '#FDF1E3',
  danger: '#B42318',
  dangerSoft: '#FEECEB',
  success: '#2E7D32',
  successSoft: '#E8F3E8',
} as const;

export const radius = { sm: 8, md: 12, lg: 16, xl: 24 } as const;

export const font = {
  family: undefined as string | undefined, // platform default (San Francisco / Roboto / Segoe UI)
  size: { xs: 11, sm: 12, md: 14, lg: 16, xl: 20, xxl: 26, hero: 40 },
} as const;

/** The brand mark: an airflow that forms a "C" (white outer stream, teal inner stream). */
import Svg, { G, Path, Rect } from 'react-native-svg';

import { colors } from './theme';

export function Logo({ size = 40 }: { size?: number }) {
  return (
    <Svg width={size} height={size} viewBox="0 0 64 64">
      <Rect width={64} height={64} rx={16} fill={colors.primary} />
      <G transform="translate(-1.5 2)" fill="none" strokeWidth={5.5} strokeLinecap="round">
        <Path stroke="#FFFFFF" d="M44 16.5a3.5 3.5 0 1 1 3.5 3.5A17 17 0 1 0 47.5 44h5" />
        <Path stroke={colors.logoAir} d="M39 27.5a7.5 7.5 0 1 0 0 9" />
      </G>
    </Svg>
  );
}

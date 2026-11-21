/** The brand mark: airflow lines in sand on a deep petrol square. */
import Svg, { G, Path, Rect } from 'react-native-svg';

import { colors } from './theme';

export function Logo({ size = 40 }: { size?: number }) {
  return (
    <Svg width={size} height={size} viewBox="0 0 64 64">
      <Rect width={64} height={64} rx={16} fill={colors.primaryDark} />
      <G transform="translate(0 2.5)" fill="none" stroke={colors.sand} strokeWidth={5} strokeLinecap="round">
        <Path d="M14 25h22a6.5 6.5 0 1 0-6.5-6.5" />
        <Path d="M14 34h30a6.5 6.5 0 1 1-6.5 6.5" />
        <Path d="M14 43h12" />
      </G>
    </Svg>
  );
}

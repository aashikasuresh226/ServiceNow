import { Platform } from 'react-native';

/**
 * Props that hide a purely decorative graphic from screen readers, in the form each
 * platform understands (react-native-svg passes props straight to the DOM on web).
 */
export const decorative =
  Platform.OS === 'web'
    ? ({ 'aria-hidden': true } as const)
    : ({ accessibilityElementsHidden: true, importantForAccessibility: 'no-hide-descendants' } as const);

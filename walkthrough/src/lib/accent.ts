import type { Accent } from '../flows/types';

// Maps a flow accent onto the exact Wardress token values. Kept as literal
// hex/rgba (not Tailwind classes) so React Flow edges and inline glows can
// consume them directly.
export interface AccentTokens {
  color: string;
  glow: string;
}

export const ACCENTS: Record<Accent, AccentTokens> = {
  blue: { color: '#3b9eff', glow: 'rgba(0, 117, 255, 0.34)' },
  orange: { color: '#ff801f', glow: 'rgba(255, 89, 0, 0.22)' },
  red: { color: '#ff2047', glow: 'rgba(255, 32, 71, 0.34)' },
  green: { color: '#11ff99', glow: 'rgba(34, 255, 153, 0.18)' },
  neutral: { color: '#888e90', glow: 'rgba(255, 255, 255, 0.10)' },
};

export const accentOf = (a: Accent): AccentTokens => ACCENTS[a];

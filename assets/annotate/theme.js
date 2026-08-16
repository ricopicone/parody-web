/**
 * Dark mode for a document that is white paper.
 *
 * The rule everywhere here: invert the PAPER and the near-black ink, and leave
 * authored colour alone. In these books colour means something — circuit
 * figures use blue and green accents, boxed environments are colour-coded by
 * type — so a straight invert would turn a blue definition box orange and say
 * something false. pdf.js applies the same rule to the page itself through its
 * pageColors/High Contrast filter; this module applies it to the reader's ink.
 *
 * Display only. The stored stroke colour never changes, which is what keeps a
 * downloaded PDF in light mode regardless of how it was read.
 */

/**
 * Relative luminance, 0 (black) to 1 (white), or null when the colour cannot
 * be read.
 *
 * null rather than 0: returning 0 would make anything unparseable look like
 * black and get flipped to light ink on a dark page. An unknown colour is left
 * exactly as it is.
 */
export function luminance(hex) {
  const value = String(hex || '').replace('#', '');
  const full = value.length === 3
    ? value.split('').map((c) => c + c).join('')
    : value;
  if (!/^[0-9a-fA-F]{6}$/.test(full)) return null;
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16) / 255);
  // sRGB coefficients; good enough to answer "is this ink or is this paper".
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export const NEAR_BLACK = 0.18;
export const NEAR_WHITE = 0.82;

export function isNearBlack(hex) {
  const value = luminance(hex);
  return value !== null && value <= NEAR_BLACK;
}

export function isNearWhite(hex) {
  const value = luminance(hex);
  return value !== null && value >= NEAR_WHITE;
}

/**
 * The colour to DRAW a stroke in, given the current theme.
 *
 * Only the two ends of the scale move: black ink would be invisible on dark
 * paper, and white ink invisible on light. Everything the reader deliberately
 * chose — blue, red, green, orange, purple — stays exactly as chosen, on both
 * backgrounds.
 */
export function displayColor(hex, { dark, ink, paper }) {
  if (!dark) return hex;
  if (isNearBlack(hex)) return ink;
  if (isNearWhite(hex)) return paper;
  return hex;
}

/** Read the site's own theme tokens, so the PDF matches the page around it. */
export function themeColors(root = document.documentElement) {
  const styles = getComputedStyle(root);
  const value = (name, fallback) =>
    (styles.getPropertyValue(name) || '').trim() || fallback;
  return { paper: value('--paper', '#ffffff'), ink: value('--ink', '#111111') };
}

/** Is the reader in dark mode? Their explicit choice wins over the OS. */
export function isDark(root = document.documentElement) {
  const chosen = root.dataset.theme;
  if (chosen === 'dark') return true;
  if (chosen === 'light') return false;
  return !!(window.matchMedia
            && window.matchMedia('(prefers-color-scheme: dark)').matches);
}

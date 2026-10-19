/**
 * A zoom that fits the row on screen.
 *
 * Reading a translation beside the English puts two pages in each row, which
 * at the default zoom is wider than a laptop. The reader should see both
 * pages without scrolling sideways, so the viewer starts at the largest rung
 * of the zoom ladder at which the row fits — never above 1, which is the
 * size a single page is read at, and never off the ladder, so + and − carry
 * on from it as they would from any other rung.
 *
 * `widthAtOne` is the row's width at zoom 1, `available` the width it has.
 */
export function fitZoom(widthAtOne, available, steps) {
  if (!(widthAtOne > 0) || !(available > 0)) return 1;
  const fits = steps.filter((z) => z <= 1 && widthAtOne * z <= available);
  return fits.length ? Math.max(...fits) : Math.min(...steps);
}

/**
 * Below this, two pages side by side are too small to read comfortably (10pt
 * type at 0.75 of the reader's 1.25 is about 9px), and one page under the
 * other at a readable size is better than both in view at an unreadable one.
 */
export const MIN_BESIDE = 0.75;

/**
 * Whether the translation goes beside each page or under it, and the zoom
 * that fits: beside when both pages fit at MIN_BESIDE or more, else under.
 * Under, never below MIN_BESIDE either: on a phone a page that does not fit
 * scrolls sideways a little, as the English alone does, rather than shrink
 * past reading. `besideAtOne` and `stackedAtOne` are the row's widths at
 * zoom 1 each way.
 */
export function twinLayout(besideAtOne, stackedAtOne, available, steps) {
  const beside = fitZoom(besideAtOne, available, steps);
  if (besideAtOne * beside <= available && beside >= MIN_BESIDE) {
    return { stacked: false, zoom: beside };
  }
  return { stacked: true, zoom: Math.max(fitZoom(stackedAtOne, available, steps), MIN_BESIDE) };
}

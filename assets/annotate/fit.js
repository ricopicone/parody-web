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

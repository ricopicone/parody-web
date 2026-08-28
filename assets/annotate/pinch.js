/**
 * Pinch-to-zoom, in the viewer's own zoom rather than the browser's.
 *
 * The browser's pinch magnifies the whole application — the reader zooms in
 * on a figure and the toolbar goes off-screen with everything else. What a
 * reader means by pinching a page is the zoom the + and − buttons drive, so
 * the gesture is taken over and mapped onto that same ladder.
 *
 * It snaps to the rungs rather than scaling smoothly because a zoom re-renders
 * every visible page (see PageView.setZoom): a continuous gesture would ask
 * pdf.js for a new rasterisation on every frame. Snapping means one render per
 * rung crossed, and it lands on exactly the values the buttons reach.
 */

/** Distance between the first two touches, in CSS pixels. */
export function pinchDistance(touches) {
  const [a, b] = [touches[0], touches[1]];
  return Math.hypot(b.clientX - a.clientX, b.clientY - a.clientY);
}

/** The point the gesture is centred on. */
export function pinchMidpoint(touches) {
  const [a, b] = [touches[0], touches[1]];
  return { x: (a.clientX + b.clientX) / 2, y: (a.clientY + b.clientY) / 2 };
}

/**
 * The rung this gesture has reached: the step nearest where a smooth zoom
 * would be, so spreading picks up magnification steadily rather than only
 * once the fingers pass some threshold.
 */
export function stepFor(startZoom, ratio, steps) {
  const target = startZoom * ratio;
  return steps.reduce(
    (best, z) => (Math.abs(z - target) < Math.abs(best - target) ? z : best),
    steps[0]);
}

/**
 * Where to scroll so the content under the fingers stays under them.
 *
 * Without this the page grows from wherever the scrollbar happens to sit, and
 * the figure being pinched slides away from the fingers pinching it. `focal`
 * is measured from the scroller's own top-left corner.
 */
export function anchoredScroll(scroll, focal, from, to) {
  if (!from) return scroll;
  return ((scroll + focal) / from) * to - focal;
}

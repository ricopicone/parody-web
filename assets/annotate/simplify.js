/**
 * Throwing away the vertices the drawn shape never needed.
 *
 * A pen reports around 240 times a second and `freehandPath` builds an outline
 * from every one of those samples, so a long mark cost 23 KB of path. A reader
 * who annotated for one evening was pushing 16.7 MB at the server (task #667).
 *
 * This thins the OUTLINE, not the input samples. That distinction is the whole
 * design, and it was arrived at the hard way:
 *
 * Simplifying the input first looks better on paper — the outline carries
 * about twice the points of its input and each costs four numbers, so a
 * dropped sample seems worth eight numbers saved. It is not safe. perfect-
 * freehand derives each point's radius from how far the pen travelled since
 * the last sample (and, under `simulatePressure`, invents pressure from the
 * same signal), so removing samples changes the width along the whole stroke.
 * Measured against the unsimplified outline, dropping input at a 0.05pt
 * tolerance moved the drawn edge by 6.3pt — 2 mm, plainly visible — and
 * tightening the tolerance did not help, because the error never came from the
 * tolerance.
 *
 * Thinning the finished outline has no such indirection. Ramer–Douglas–Peucker
 * bounds the distance from every discarded vertex to the line that replaces
 * it, so the error is whatever tolerance we ask for and nothing more. Measured
 * deviation tracks the tolerance to three decimal places.
 */

/**
 * How far the drawn edge may move, in PDF points (1pt = 1/72in).
 *
 * 0.2pt is 0.070 mm — under a fifth of the narrowest line the pen draws, and
 * finer than any zoom the viewer offers can resolve. Rounding coordinates to
 * one decimal adds at most another 0.05pt.
 */
export const SIMPLIFY_TOLERANCE = 0.2;

/** Distance from a point to a segment. */
function pointToSegment(px, py, ax, ay, bx, by) {
  const dx = bx - ax;
  const dy = by - ay;
  const len2 = dx * dx + dy * dy;
  const t = len2 === 0
    ? 0
    : Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / len2));
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

/**
 * Fewer vertices describing the same closed outline.
 *
 * Iterative rather than recursive: an outline can run to a couple of thousand
 * vertices and this is called on every completed gesture.
 */
export function simplify(points, tolerance = SIMPLIFY_TOLERANCE) {
  if (!Array.isArray(points) || points.length < 3) return points;

  const keep = new Uint8Array(points.length);
  keep[0] = 1;
  keep[points.length - 1] = 1;

  const stack = [[0, points.length - 1]];
  while (stack.length) {
    const [lo, hi] = stack.pop();
    if (hi - lo < 2) continue;
    const [ax, ay] = points[lo];
    const [bx, by] = points[hi];
    let worst = 0;
    let at = lo;
    for (let i = lo + 1; i < hi; i++) {
      const d = pointToSegment(points[i][0], points[i][1], ax, ay, bx, by);
      if (d > worst) { worst = d; at = i; }
    }
    if (worst <= tolerance) continue;
    keep[at] = 1;
    stack.push([lo, at], [at, hi]);
  }

  const out = [];
  for (let i = 0; i < points.length; i++) if (keep[i]) out.push(points[i]);
  return out;
}

/**
 * Every tool produces an SVG path in PDF points.
 *
 * One vocabulary for the client, the store, and the server exporter: a stroke
 * is a path plus how to paint it. Pen and highlighter are closed outlines that
 * get filled; line, rect and circle are open paths that get stroked. Without
 * this the exporter would need a branch per tool, and each new tool would mean
 * touching Python as well as JavaScript.
 */
import { getStroke } from 'perfect-freehand';
import { simplify, SIMPLIFY_TOLERANCE } from './simplify.js';

export const FREEHAND_OPTIONS = {
  smoothing: 0.5,
  thinning: 0.5,
  streamline: 0.5,
  easing: (t) => t,
  simulatePressure: true,
};

// One decimal: 0.035 mm in PDF points, an order of magnitude finer than the
// line being drawn. The second decimal was 16% of every path and could not
// be seen at any zoom the viewer offers.
const n = (v) => (Math.round(v * 10) / 10);

/** perfect-freehand's outline as an SVG path — the shape the ink really is. */
export function freehandPath(points, size) {
  // Thin the outline, never the input samples: perfect-freehand derives width
  // from sample spacing, so dropping samples moves the drawn edge by millimetres
  // however tight the tolerance. See simplify.js.
  const outline = simplify(getStroke(points, { ...FREEHAND_OPTIONS, size }),
                           SIMPLIFY_TOLERANCE);
  if (!outline.length) return '';
  const d = outline.reduce((acc, [x0, y0], i, arr) => {
    const [x1, y1] = arr[(i + 1) % arr.length];
    acc.push(n(x0), n(y0), n((x0 + x1) / 2), n((y0 + y1) / 2));
    return acc;
  }, ['M', n(outline[0][0]), n(outline[0][1]), 'Q']);
  return `${d.join(' ')} Z`;
}

export function linePath(x1, y1, x2, y2) {
  return `M ${n(x1)} ${n(y1)} L ${n(x2)} ${n(y2)}`;
}

export function rectPath(x, y, w, h) {
  return `M ${n(x)} ${n(y)} L ${n(x + w)} ${n(y)} `
       + `L ${n(x + w)} ${n(y + h)} L ${n(x)} ${n(y + h)} Z`;
}

/** An ellipse as four cubic segments — the standard 0.5523 circle constant. */
export function ellipsePath(cx, cy, rx, ry) {
  const k = 0.5522847498;
  const ox = rx * k;
  const oy = ry * k;
  return [
    `M ${n(cx - rx)} ${n(cy)}`,
    `C ${n(cx - rx)} ${n(cy - oy)} ${n(cx - ox)} ${n(cy - ry)} ${n(cx)} ${n(cy - ry)}`,
    `C ${n(cx + ox)} ${n(cy - ry)} ${n(cx + rx)} ${n(cy - oy)} ${n(cx + rx)} ${n(cy)}`,
    `C ${n(cx + rx)} ${n(cy + oy)} ${n(cx + ox)} ${n(cy + ry)} ${n(cx)} ${n(cy + ry)}`,
    `C ${n(cx - ox)} ${n(cy + ry)} ${n(cx - rx)} ${n(cy + oy)} ${n(cx - rx)} ${n(cy)}`,
    'Z',
  ].join(' ');
}

/** Build the stored stroke for a completed gesture. */
export function buildStroke(tool, { points, from, to, color, size, opacity }) {
  const common = { tool, color, opacity };
  if (tool === 'pen' || tool === 'highlighter') {
    // The outline is the stroke. The raw samples are deliberately NOT stored:
    // nothing reads them — the canvas draws `d`, the eraser hit-tests the
    // bounds parsed out of `d`, and the Python exporter renders `d` — while
    // they cost about a third of every stroke on the wire, unrounded pressure
    // floats and all. A save carries the whole section, so that third is what
    // pushed a well-annotated one past the request-body ceiling (task #667).
    //
    return { ...common, size, d: freehandPath(points, size) };
  }
  const shape = { ...common, mode: 'stroke', width: size };
  if (tool === 'line') return { ...shape, d: linePath(from.x, from.y, to.x, to.y) };
  if (tool === 'rect') {
    return { ...shape, d: rectPath(Math.min(from.x, to.x), Math.min(from.y, to.y),
                                   Math.abs(to.x - from.x), Math.abs(to.y - from.y)) };
  }
  if (tool === 'circle') {
    return { ...shape, d: ellipsePath((from.x + to.x) / 2, (from.y + to.y) / 2,
                                      Math.abs(to.x - from.x) / 2,
                                      Math.abs(to.y - from.y) / 2) };
  }
  return null;
}

/** Rough bounding box of a stored stroke, for hit-testing the eraser. */
export function bounds(stroke) {
  const nums = (stroke.d || '').match(/-?\d*\.?\d+/g);
  if (!nums || nums.length < 2) return null;
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (let i = 0; i + 1 < nums.length; i += 2) {
    const x = parseFloat(nums[i]);
    const y = parseFloat(nums[i + 1]);
    if (x < minX) minX = x;
    if (y < minY) minY = y;
    if (x > maxX) maxX = x;
    if (y > maxY) maxY = y;
  }
  return { minX, minY, maxX, maxY };
}

/** Does a stroke fall within `radius` of a point? Used by the eraser. */
export function hits(stroke, x, y, radius) {
  const box = bounds(stroke);
  if (!box) return false;
  return x >= box.minX - radius && x <= box.maxX + radius
      && y >= box.minY - radius && y <= box.maxY + radius;
}

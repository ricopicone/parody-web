import test from 'node:test';
import assert from 'node:assert/strict';
import { getStroke } from 'perfect-freehand';
import { simplify, SIMPLIFY_TOLERANCE } from './simplify.js';
import { buildStroke, freehandPath, FREEHAND_OPTIONS } from './shapes.js';

/** A long continuous mark at pen sampling rate — the shape that costs. */
function mark(nSamples, pressure) {
  const pts = [];
  for (let i = 0; i < nSamples; i++) {
    const t = i / nSamples;
    pts.push([80 + 400 * t + 6 * Math.sin(t * 30),
              300 + 60 * Math.sin(t * 12),
              pressure ? pressure(t) : (128 + Math.round(60 * Math.sin(t * 9))) / 255]);
  }
  return pts;
}
/** Handwriting: short, tight, curvy — the other end of the spectrum. */
function script(nSamples) {
  const pts = [];
  for (let i = 0; i < nSamples; i++) {
    const t = i / nSamples;
    pts.push([100 + 40 * t + 5 * Math.sin(t * 90),
              300 + 8 * Math.sin(t * 120), 0.5 + 0.2 * Math.sin(t * 30)]);
  }
  return pts;
}

function pointToSegment(px, py, ax, ay, bx, by) {
  const dx = bx - ax, dy = by - ay, len2 = dx * dx + dy * dy;
  const t = len2 === 0 ? 0
    : Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / len2));
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}
function devToPolyline(a, b) {
  let worst = 0;
  for (const [px, py] of a) {
    let near = Infinity;
    for (let i = 0; i < b.length; i++) {
      const [ax, ay] = b[i];
      const [bx, by] = b[(i + 1) % b.length];
      near = Math.min(near, pointToSegment(px, py, ax, ay, bx, by));
    }
    worst = Math.max(worst, near);
  }
  return worst;
}
/** Symmetric: neither shape may stray from the other. */
const hausdorff = (a, b) => Math.max(devToPolyline(a, b), devToPolyline(b, a));

const outlineOf = (pts, size) => getStroke(pts, { ...FREEHAND_OPTIONS, size });

test('it keeps the endpoints exactly', () => {
  const o = outlineOf(mark(400), 2);
  const out = simplify(o, SIMPLIFY_TOLERANCE);
  assert.deepEqual(out[0], o[0]);
  assert.deepEqual(out.at(-1), o.at(-1));
});

test('an outline too short to thin comes back untouched', () => {
  assert.deepEqual(simplify([], SIMPLIFY_TOLERANCE), []);
  const one = [[1, 2]];
  assert.deepEqual(simplify(one, SIMPLIFY_TOLERANCE), one);
  const two = [[1, 2], [3, 4]];
  assert.deepEqual(simplify(two, SIMPLIFY_TOLERANCE), two);
});

test('a straight run collapses to its two ends', () => {
  const line = Array.from({ length: 50 }, (_, i) => [i, 0]);
  assert.equal(simplify(line, SIMPLIFY_TOLERANCE).length, 2);
});

test('the drawn edge never moves further than the tolerance', () => {
  // This is the guarantee the whole approach rests on, and the reason we thin
  // the outline rather than the input: RDP bounds the distance from every
  // discarded vertex to the line that replaces it. Simplifying the input
  // instead moved the edge by 6.3pt at a 0.05pt tolerance, because
  // perfect-freehand derives width from sample spacing (task #667).
  for (const [pts, size] of [[mark(700), 2], [script(220), 2], [mark(400), 12]]) {
    const full = outlineOf(pts, size);
    const thin = simplify(full, SIMPLIFY_TOLERANCE);
    const moved = hausdorff(thin, full);
    assert.ok(moved <= SIMPLIFY_TOLERANCE + 1e-6,
              `edge moved ${moved.toFixed(3)}pt at size ${size}`);
  }
});

test('the tolerance is finer than the ink it describes', () => {
  // 0.2pt is 0.070 mm. The narrowest line the pen draws is an order of
  // magnitude wider, so this is not a judgement call about taste.
  assert.ok(SIMPLIFY_TOLERANCE * 25.4 / 72 < 0.1);
});

test('a long mark loses most of its vertices', () => {
  const full = outlineOf(mark(700), 2);
  const thin = simplify(full, SIMPLIFY_TOLERANCE);
  assert.ok(thin.length < full.length * 0.25,
            `kept ${thin.length} of ${full.length}`);
});

test('buildStroke emits a materially smaller path than it used to', () => {
  const s = buildStroke('pen', { points: mark(700), color: '#111', size: 2, opacity: 1 });
  // 27363 B before this work (2dp, no thinning); 22847 B after the 1dp change.
  assert.ok(s.d.length < 27363 * 0.3, `d is ${s.d.length} B`);
});

test('coordinates are written to one decimal', () => {
  const d = freehandPath(mark(50), 2);
  const nums = d.match(/-?\d+\.\d+/g) || [];
  assert.ok(nums.length > 0);
  for (const v of nums) {
    assert.ok(v.split('.')[1].length <= 1, `${v} has more than one decimal`);
  }
});

test('the path is still a closed filled outline', () => {
  // The exporter and the canvas both depend on this shape; thinning must not
  // change the vocabulary, only the number of vertices in it.
  const d = freehandPath(mark(300), 2);
  assert.ok(d.startsWith('M '));
  assert.ok(d.includes(' Q '));
  assert.ok(d.endsWith(' Z'));
});

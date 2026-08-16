import test from 'node:test';
import assert from 'node:assert/strict';
import { linePath, rectPath, ellipsePath, buildStroke, bounds, hits }
  from './shapes.js';

test('a line is a two-point path', () => {
  assert.equal(linePath(0, 0, 10, 20), 'M 0 0 L 10 20');
});

test('a rect closes itself', () => {
  assert.equal(rectPath(0, 0, 10, 5), 'M 0 0 L 10 0 L 10 5 L 0 5 Z');
});

test('an ellipse is four cubics and closes', () => {
  const d = ellipsePath(50, 50, 10, 20);
  assert.equal((d.match(/C/g) || []).length, 4);
  assert.ok(d.endsWith('Z'));
});

test('a shape is stroked and carries its width', () => {
  const s = buildStroke('line', { from: { x: 0, y: 0 }, to: { x: 1, y: 1 },
                                  color: '#000', size: 3, opacity: 1 });
  assert.equal(s.mode, 'stroke');
  assert.equal(s.width, 3);
});

test('a pen stroke is a filled outline and keeps its input points', () => {
  const s = buildStroke('pen', { points: [[0, 0, 0.5], [5, 5, 0.6], [9, 2, 0.7]],
                                 color: '#000', size: 2, opacity: 1 });
  assert.equal(s.mode, undefined);          // filled, not stroked
  assert.equal(s.points.length, 3);         // kept, so it can be re-edited
  assert.ok(s.d.startsWith('M'));
  assert.ok(s.d.endsWith('Z'));             // closed outline
});

test('a rect drawn right-to-left still has positive extents', () => {
  const s = buildStroke('rect', { from: { x: 10, y: 10 }, to: { x: 0, y: 0 },
                                  color: '#000', size: 1, opacity: 1 });
  assert.equal(s.d, 'M 0 0 L 10 0 L 10 10 L 0 10 Z');
});

test('bounds covers the path', () => {
  assert.deepEqual(bounds({ d: 'M 0 0 L 10 20' }),
                   { minX: 0, minY: 0, maxX: 10, maxY: 20 });
});

test('the eraser hits near a stroke and misses far from it', () => {
  const s = { d: 'M 0 0 L 10 10' };
  assert.equal(hits(s, 5, 5, 3), true);
  assert.equal(hits(s, 40, 40, 3), false);
});

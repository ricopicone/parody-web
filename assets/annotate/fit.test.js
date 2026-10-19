import test from 'node:test';
import assert from 'node:assert/strict';
import { fitZoom } from './fit.js';

const STEPS = [0.6, 0.75, 0.9, 1, 1.15, 1.35];

test('the largest rung at which the row fits, never above 1', () => {
  // two 540px pages and a 16px gap need 1096px at zoom 1
  assert.equal(fitZoom(1096, 1440, STEPS), 1);
  assert.equal(fitZoom(1096, 1024, STEPS), 0.9);
  assert.equal(fitZoom(1096, 900, STEPS), 0.75);
});

test('when nothing fits, the smallest rung', () => {
  assert.equal(fitZoom(1096, 300, STEPS), 0.6);
});

test('a width it cannot measure leaves the zoom alone', () => {
  assert.equal(fitZoom(0, 1440, STEPS), 1);
  assert.equal(fitZoom(1096, 0, STEPS), 1);
});

// ---- beside, or under ----------------------------------------------------

import { twinLayout, MIN_BESIDE } from './fit.js';

test('two 6x9 pages sit side by side on a laptop', () => {
  assert.deepEqual(twinLayout(1092, 540, 1384, STEPS), { stacked: false, zoom: 1 });
  assert.deepEqual(twinLayout(1092, 540, 1008, STEPS), { stacked: false, zoom: 0.9 });
});

test('pages too small to read side by side go one under the other', () => {
  // an iPad in portrait: side by side needs 0.6, below what reads comfortably
  assert.equal(1092 * MIN_BESIDE > 752, true);
  assert.deepEqual(twinLayout(1092, 540, 752, STEPS), { stacked: true, zoom: 1 });
  // letter pages on an iPad in landscape: stacked, and the page at full size
  assert.deepEqual(twinLayout(1542, 765, 1008, STEPS), { stacked: true, zoom: 1 });
});

test('stacked on a phone, the page is fitted, but never below what reads', () => {
  // 0.6 made 11pt type about 8px: turning a translation on shrank the English
  // the student was reading, which English alone opens at 1
  assert.deepEqual(twinLayout(1092, 540, 374, STEPS), { stacked: true, zoom: MIN_BESIDE });
  assert.deepEqual(twinLayout(1092, 540, 420, STEPS), { stacked: true, zoom: 0.75 });
});

import test from 'node:test';
import assert from 'node:assert/strict';
import { pinchDistance, pinchMidpoint, stepFor, anchoredScroll } from './pinch.js';

const STEPS = [0.6, 0.75, 0.9, 1, 1.15, 1.35, 1.6, 2, 2.5, 3];
const touches = (...pts) => pts.map(([x, y]) => ({ clientX: x, clientY: y }));

test('the gesture is measured between the two fingers', () => {
  assert.equal(pinchDistance(touches([0, 0], [3, 4])), 5);
  assert.deepEqual(pinchMidpoint(touches([0, 0], [10, 20])), { x: 5, y: 10 });
});

test('a third finger does not change the measurement', () => {
  // A hand on the glass while pinching is common; the first two win.
  assert.equal(pinchDistance(touches([0, 0], [3, 4], [90, 90])), 5);
});

test('holding still stays on the rung it started from', () => {
  assert.equal(stepFor(1, 1, STEPS), 1);
  assert.equal(stepFor(1.35, 1, STEPS), 1.35);
});

test('spreading climbs the same ladder the + button climbs', () => {
  // Every value it can return is a value the buttons reach — that is what
  // "the same zoom" means here.
  for (const ratio of [1.1, 1.3, 1.7, 2.4, 9]) {
    assert.ok(STEPS.includes(stepFor(1, ratio, STEPS)), `ratio ${ratio}`);
  }
  assert.equal(stepFor(1, 1.4, STEPS), 1.35);
  assert.equal(stepFor(1, 2, STEPS), 2);
});

test('pinching in comes back down it', () => {
  assert.equal(stepFor(2, 0.5, STEPS), 1);
  assert.equal(stepFor(1, 0.6, STEPS), 0.6);
});

test('the ladder has ends, and a hard pinch stops at them', () => {
  assert.equal(stepFor(1, 100, STEPS), 3);
  assert.equal(stepFor(1, 0.001, STEPS), 0.6);
});

test('the ratio is applied to where the gesture STARTED', () => {
  // Not to the current zoom, or the gesture compounds itself: each frame
  // would multiply again and the page would run away from the fingers.
  assert.equal(stepFor(0.9, 1.15, STEPS), 1);
  assert.equal(stepFor(2, 1.15, STEPS), 2.5);
});

test('the content under the fingers stays under the fingers', () => {
  // A point 100px down the scroller, with 50px already scrolled past, sits
  // 150px into the content. At double the zoom it is 300px in, so it must be
  // 200px further down the scroller to still show at 100.
  assert.equal(anchoredScroll(50, 100, 1, 2), 200);
});

test('zooming out anchors the same way', () => {
  assert.equal(anchoredScroll(200, 100, 2, 1), 50);
});

test('no zoom change leaves the scroll exactly alone', () => {
  assert.equal(anchoredScroll(137, 42, 1.35, 1.35), 137);
});

test('a zero starting zoom cannot divide the scroll away', () => {
  assert.equal(anchoredScroll(137, 42, 0, 2), 137);
});

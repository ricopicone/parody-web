import test from 'node:test';
import assert from 'node:assert/strict';
import { screenToPdf, pdfToScreen, pagedTransform, pageAt, windowAround }
  from './paged.js';

test('the page origin maps to the PDF origin', () => {
  assert.deepEqual(screenToPdf(0, 0, { scale: 1 }), { x: 0, y: 0 });
});

test('zoom divides out, so ink lands in the same place at any zoom', () => {
  assert.deepEqual(screenToPdf(200, 100, { scale: 2 }), { x: 100, y: 50 });
  assert.deepEqual(screenToPdf(50, 25, { scale: 0.5 }), { x: 100, y: 50 });
});

test('screen and pdf conversions are inverses', () => {
  const there = screenToPdf(321, 654, { scale: 1.5 });
  const back = pdfToScreen(there.x, there.y, { scale: 1.5 });
  assert.equal(Math.round(back.x), 321);
  assert.equal(Math.round(back.y), 654);
});

test('device pixel ratio never reaches PDF space', () => {
  // A retina screen must not move a reader's ink.
  assert.deepEqual(screenToPdf(100, 100, { scale: 1, dpr: 3 }), { x: 100, y: 100 });
});

test('the transform subtracts the page rect and carries pressure', () => {
  const t = pagedTransform(2, { scale: 2 }, () => ({ left: 40, top: 10 }));
  assert.deepEqual(t({ clientX: 240, clientY: 110, pressure: 0.8 }),
                   { page: 2, x: 100, y: 50, pressure: 0.8 });
});

test('a mouse reporting no pressure gets a usable default', () => {
  const t = pagedTransform(1, { scale: 1 }, () => ({ left: 0, top: 0 }));
  assert.equal(t({ clientX: 1, clientY: 1, pressure: 0 }).pressure, 0.5);
});

test('pageAt finds the page a scroll position is in', () => {
  const tops = [0, 800, 1600];
  assert.equal(pageAt(0, tops), 0);
  assert.equal(pageAt(799, tops), 0);
  assert.equal(pageAt(800, tops), 1);
  assert.equal(pageAt(5000, tops), 2);
});

test('the render window is clamped to the document', () => {
  assert.deepEqual(windowAround(0, 3), [0, 1]);
  assert.deepEqual(windowAround(1, 3), [0, 1, 2]);
  assert.deepEqual(windowAround(2, 3), [1, 2]);
});

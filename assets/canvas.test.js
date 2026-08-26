import { strict as assert } from 'node:assert';
import { test } from 'node:test';
import { releaseCanvas } from './canvas.js';

const fakeCanvas = () => ({
  width: 1080, height: 1620, removed: 0, remove() { this.removed += 1; },
});

test('releasing detaches the canvas AND frees its pixels', () => {
  // .remove() alone is what every one of these sites used to do, and it frees
  // nothing: a detached canvas keeps its backing store.
  const c = fakeCanvas();
  releaseCanvas(c);
  assert.equal(c.removed, 1, 'detached');
  assert.equal(c.width, 0, 'and its pixels given back');
  assert.equal(c.height, 0);
});

test('the bytes it gives back are the whole surface', () => {
  const c = fakeCanvas();
  const before = c.width * c.height * 4;
  releaseCanvas(c);
  assert.equal(before, 6998400, '6.7 MB for one page at dpr 2');
  assert.equal(c.width * c.height * 4, 0);
});

test('releasing nothing is not an error', () => {
  // _release runs on every page outside the window, most of which hold none.
  releaseCanvas(null);
  releaseCanvas(undefined);
});

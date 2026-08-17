import { strict as assert } from 'node:assert';
import { test } from 'node:test';
import { placeReveal, toCss } from './reveal.js';

const SCALE = 2;
const PLATE = { width: 80, height: 20 };

test('a PDF box scales to CSS pixels with no y-flip', () => {
  // PyMuPDF reports top-left origin already, as the DOM expects.
  assert.deepEqual(toCss([10, 20, 30, 26], 2),
                   { x0: 20, y0: 40, x1: 60, y1: 52 });
});

test('an inverted box is normalised', () => {
  assert.deepEqual(toCss([30, 26, 10, 20], 2), toCss([10, 20, 30, 26], 2));
});

test('the plate sits above the blank, never on it', () => {
  const at = placeReveal([100, 50, 160, 56], SCALE, PLATE);
  const blankTop = 100;                       // y0 * scale
  assert.ok(at.top + PLATE.height <= blankTop,
            'plate bottom must clear the blank top');
});

test('the plate is centred on the blank', () => {
  const at = placeReveal([100, 50, 160, 56], SCALE, PLATE);
  assert.equal(at.left + PLATE.width / 2, 260);
});

test('a blank at the very top of the page flips the plate below it', () => {
  const at = placeReveal([100, 0, 160, 3], SCALE, PLATE);
  assert.ok(at.top > 0, 'must not render off the top of the page');
  assert.ok(at.top >= 6, 'must clear the blank it flipped under');
});

test('zooming in moves the plate proportionally', () => {
  const near = placeReveal([100, 50, 160, 56], 1, PLATE);
  const far = placeReveal([100, 50, 160, 56], 2, PLATE);
  assert.equal(far.left + PLATE.width / 2, (near.left + PLATE.width / 2) * 2);
});

test('a wide reveal is clamped onto the page, not off its left edge', () => {
  // A displayed equation is easily wider than the measure it is revealed over.
  const wide = { width: 400, height: 40 };
  const at = placeReveal([100, 50, 160, 56], SCALE, wide, 500);
  assert.ok(at.left >= 0, 'must not hang off the left edge');
  assert.ok(at.left + wide.width <= 500, 'must not hang off the right edge');
});

test('clamping still prefers centring when there is room', () => {
  const at = placeReveal([100, 50, 160, 56], SCALE, PLATE, 5000);
  assert.equal(at.left + PLATE.width / 2, 260);
});

test('an unknown page width still clamps the left edge', () => {
  const at = placeReveal([0, 50, 4, 56], SCALE, { width: 300, height: 20 });
  assert.ok(at.left >= 0);
});

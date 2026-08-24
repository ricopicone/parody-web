import { strict as assert } from 'node:assert';
import { test } from 'node:test';
import { BlankMarks, blanksOnPage, nextBlank } from './blanks.js';

const CLOZES = [
  { token: 1, page: 0 },
  { token: 5, page: 2 },
  { token: 9, page: 2 },
];

test('blanks are grouped by the page they sit on', () => {
  assert.deepEqual(blanksOnPage(CLOZES, 2).map((c) => c.token), [5, 9]);
  assert.deepEqual(blanksOnPage(CLOZES, 1), []);
  assert.deepEqual(blanksOnPage(undefined, 0), []);
});

test('stepping forward from nowhere lands on the first', () => {
  assert.equal(nextBlank(CLOZES, -1, 1), 0);
});

test('stepping wraps in both directions', () => {
  assert.equal(nextBlank(CLOZES, 2, 1), 0);
  assert.equal(nextBlank(CLOZES, 0, -1), 2);
});

test('stepping back from nowhere lands on the last', () => {
  assert.equal(nextBlank(CLOZES, -1, -1), 2);
});

test('a section with no blanks reports nothing to step to', () => {
  assert.equal(nextBlank([], -1, 1), -1);
  assert.equal(nextBlank(undefined, 0, 1), -1);
});

test('a clozed equation is outlined, not washed over', () => {
  // Its box is the whole derivation. A fill there is a slab of colour across
  // the maths; a one-line blank is a space to write in and keeps its wash.
  let fills = 0, strokes = 0;
  const ctx = { clearRect() {}, fillRect() { fills += 1; },
                strokeRect() { strokes += 1; }, setTransform() {},
                fillStyle: '', strokeStyle: '', lineWidth: 0 };
  const canvas = { style: {}, getContext: () => ctx, width: 100, height: 100,
                   remove() {} };
  global.document = { createElement: () => canvas };
  global.window = { devicePixelRatio: 1 };
  const page = { el: { offsetWidth: 100, offsetHeight: 100, appendChild() {} },
                 scale: 1 };
  const marks = new BlankMarks(page);
  marks.setBoxes([{ token: 1, kind: 'math_cloze', x0: 1, y0: 2, x1: 90, y1: 80 },
                  { token: 2, kind: 'cloze', x0: 1, y0: 90, x1: 40, y1: 92 }]);
  assert.equal(fills, 1, 'only the ordinary blank is washed');
  assert.equal(strokes, 1, 'only the equation is outlined');
});

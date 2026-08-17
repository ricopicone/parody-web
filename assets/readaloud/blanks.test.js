import { strict as assert } from 'node:assert';
import { test } from 'node:test';
import { blanksOnPage, nextBlank } from './blanks.js';

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

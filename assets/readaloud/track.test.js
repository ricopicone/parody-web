import { strict as assert } from 'node:assert';
import { test } from 'node:test';
import { clozeAt, showable, wordAt } from './track.js';

const WORDS = [
  { start_ms: 0, end_ms: 100 },
  { start_ms: 100, end_ms: 250 },
  { start_ms: 250, end_ms: 400 },
];

test('finds the word being spoken', () => {
  assert.equal(wordAt(WORDS, 0), 0);
  assert.equal(wordAt(WORDS, 99), 0);
  assert.equal(wordAt(WORDS, 150), 1);
  assert.equal(wordAt(WORDS, 399), 2);
});

test('before the first and after the last are misses', () => {
  assert.equal(wordAt(WORDS, -1), -1);
  assert.equal(wordAt(WORDS, 900), -1);
});

test('an empty track never matches', () => {
  assert.equal(wordAt([], 10), -1);
});

test('a cloze is due once its answer has finished being spoken', () => {
  const clozes = [{ token: 4, start_ms: 100, end_ms: 250 }];
  assert.equal(clozeAt(clozes, 90), -1);
  assert.equal(clozeAt(clozes, 249), -1);
  assert.equal(clozeAt(clozes, 250), 0);
  assert.equal(clozeAt(clozes, 9000), 0);
});

test('later clozes supersede earlier ones', () => {
  const clozes = [
    { token: 1, end_ms: 100 },
    { token: 5, end_ms: 500 },
  ];
  assert.equal(clozeAt(clozes, 120), 0);
  assert.equal(clozeAt(clozes, 500), 1);
});

test('no clozes is never due', () => {
  assert.equal(clozeAt([], 500), -1);
});

test('a cloze with no box is not showable', () => {
  const clozes = [
    { token: 1, page: 0, x0: 10 },
    { token: 2 },
    { token: 3, page: 1, x0: 0 },
  ];
  assert.deepEqual(showable(clozes).map((c) => c.token), [1, 3]);
});

test('showable copes with a missing list', () => {
  assert.deepEqual(showable(undefined), []);
});

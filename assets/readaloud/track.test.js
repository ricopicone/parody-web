import { strict as assert } from 'node:assert';
import { test } from 'node:test';
import { clozeAt, nextSentence, regionAt, revealAt, showable, skipTarget, wordAt } from './track.js';

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

const REGIONS = [
  { token: 3, start_ms: 1000, end_ms: 4000 },
  { token: 9, start_ms: 8000, end_ms: 9000 },
];

test('finds the maths being spoken now', () => {
  assert.equal(regionAt(REGIONS, 2000).token, 3);
  assert.equal(regionAt(REGIONS, 8500).token, 9);
  assert.equal(regionAt(REGIONS, 6000), null);
});

test('skipping lands at the end of the current expression', () => {
  assert.equal(skipTarget(REGIONS, 2000), 4000);
});

test('skipping just before an expression still skips it', () => {
  // Pressing skip as the equation begins is the common case.
  assert.equal(skipTarget(REGIONS, 7200), 9000);
});

test('skipping in open prose does nothing', () => {
  assert.equal(skipTarget(REGIONS, 6000), null);
  assert.equal(skipTarget([], 100), null);
});

test('skipping never goes backwards', () => {
  const target = skipTarget(REGIONS, 8999);
  assert.ok(target === null || target >= 8999);
});

test('the reveal follows the voice, not the pause', () => {
  const clozes = [{ token: 4, start_ms: 1000, end_ms: 2500 }];
  assert.equal(revealAt(clozes, 999), -1);
  assert.equal(revealAt(clozes, 1000), 0, 'visible as the answer begins');
  assert.equal(revealAt(clozes, 2499), 0, 'still visible as it ends');
  // The pause is the other signal, and it lands only once it is finished.
  assert.equal(clozeAt(clozes, 1000), -1);
  assert.equal(clozeAt(clozes, 2500), 0);
});

test('nothing is revealed in open prose', () => {
  assert.equal(revealAt([{ start_ms: 0, end_ms: 10 }], 500), -1);
  assert.equal(revealAt([], 5), -1);
});

const SENT = [
  { word: 'The',    start_ms: 0,    end_ms: 100 },
  { word: 'first.', start_ms: 100,  end_ms: 200 },
  { word: 'A',      start_ms: 200,  end_ms: 300 },
  { word: 'second.',start_ms: 300,  end_ms: 400 },
  { word: 'Third',  start_ms: 400,  end_ms: 500 },
];

test('skip lands on the start of the next sentence', () => {
  assert.equal(nextSentence(SENT, 50), 200);
  assert.equal(nextSentence(SENT, 250), 400);
});

test('there is nothing to skip to in the last sentence', () => {
  assert.equal(nextSentence(SENT, 450), null);
  assert.equal(nextSentence([], 0), null);
});

test('skip works in open prose, not only over maths', () => {
  // The whole point of the change: wanting to move on is not something that
  // only happens during an equation.
  assert.equal(skipTarget([], 50, SENT), 200);
});

test('maths still wins when we are inside one', () => {
  const regions = [{ start_ms: 40, end_ms: 90 }];
  assert.equal(skipTarget(regions, 50, SENT), 90);
});

test('skip falls back to a fixed jump when no sentence end is ahead', () => {
  // Polly's marks do not always carry the punctuation, which made the control
  // appear in some passages and vanish in others for no visible reason.
  const noPunct = [
    { word: 'one', start_ms: 0, end_ms: 100 },
    { word: 'two', start_ms: 100, end_ms: 200 },
    { word: 'three', start_ms: 200, end_ms: 30000 },
  ];
  assert.equal(nextSentence(noPunct, 50, 6000), 6050);
});

test('skip is offered until the very end, then stops', () => {
  const words = [{ word: 'a', start_ms: 0, end_ms: 5000 }];
  assert.equal(nextSentence(words, 4500), null);
});

test('a real sentence end still wins over the fallback', () => {
  const words = [
    { word: 'end.', start_ms: 0, end_ms: 100 },
    { word: 'Next', start_ms: 100, end_ms: 9000 },
  ];
  assert.equal(nextSentence(words, 50, 6000), 100);
});

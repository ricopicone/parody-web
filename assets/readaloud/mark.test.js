import { strict as assert } from 'node:assert';
import { test } from 'node:test';
import { MarkState } from './mark.js';

test('a word is drawn once, not on every frame', () => {
  const m = new MarkState();
  assert.equal(m.needs(7), true);
  m.drew(7);
  for (let i = 0; i < 60; i += 1) assert.equal(m.needs(7), false);
});

test('the next word is drawn', () => {
  const m = new MarkState();
  m.drew(7);
  assert.equal(m.needs(8), true);
});

test('a word whose page was not ready is drawn when it is', () => {
  // THE BUG. paint() recorded `painted = index` BEFORE it knew whether it
  // could draw — and it cannot when the page has no rendered canvas yet.
  // pdf.js rasterises asynchronously, so every word spoken in the gap after a
  // scroll was marked painted and then skipped for its whole duration. The
  // mark only reappeared when the voice moved on.
  const m = new MarkState();
  assert.equal(m.needs(7), true);
  // ... layerFor returned null: nothing was drawn, so nothing is remembered.
  assert.equal(m.needs(7), true, 'still owed a mark');
  m.drew(7);
  assert.equal(m.needs(7), false);
});

test('an equation is redrawn while the voice is still inside it', () => {
  // One equation is one token with one box and the voice can be in it for a
  // minute; the mark shows progress THROUGH it, so the word not changing is
  // not a reason to stop.
  const m = new MarkState();
  m.drew(7);
  assert.equal(m.needs(7, true), true);
});

test('nothing is owed when no word is being spoken', () => {
  const m = new MarkState();
  assert.equal(m.needs(-1), false);
  assert.equal(m.needs(-1, true), false);
});

test('a mark that has been taken off the page is owed again', () => {
  // The layer is destroyed whenever its page stops being rendered, and every
  // layer is cleared when the audio ends. The mark is gone from the screen;
  // remembering that it was drawn is how it never came back.
  const m = new MarkState();
  m.drew(7);
  m.invalidate();
  assert.equal(m.needs(7), true);
});

test('a zoom owes every mark again, the word having not moved', () => {
  const m = new MarkState();
  m.drew(7);
  m.invalidate();
  assert.equal(m.needs(7), true);
});

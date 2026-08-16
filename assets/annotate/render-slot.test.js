import test from 'node:test';
import assert from 'node:assert/strict';
import { Generation, RenderSlot } from './render-slot.js';

test('one render at a time', () => {
  const slot = new RenderSlot();
  assert.equal(slot.free, true);
  slot.claim();
  assert.equal(slot.free, false);
});

test('a finished render frees the slot', () => {
  const slot = new RenderSlot();
  const claim = slot.claim();
  slot.finish(claim);
  assert.equal(slot.free, true);
});

test('releasing frees the slot at once, before any cancellation settles', () => {
  // The blank-page bug: the replacement render runs synchronously after the
  // release, so the slot must already be free.
  const slot = new RenderSlot();
  slot.claim();
  slot.release();
  assert.equal(slot.free, true);
});

test('a cancelled render cannot free the slot its replacement holds', () => {
  const slot = new RenderSlot();
  const stale = slot.claim();
  slot.release();
  const fresh = slot.claim();
  slot.finish(stale);             // the cancellation finally settles
  assert.equal(slot.free, false, 'the fresh render still owns the slot');
  slot.finish(fresh);
  assert.equal(slot.free, true);
});

test('work begun before a zoom may not attach', () => {
  const slot = new RenderSlot();
  const claim = slot.claim();
  assert.equal(slot.canAttach(claim), true);
  slot.invalidate();
  assert.equal(slot.canAttach(claim), false);
});

test('work begun after a zoom may attach', () => {
  const slot = new RenderSlot();
  slot.invalidate();
  assert.equal(slot.canAttach(slot.claim()), true);
});

test('the full zoom sequence: two quick clicks leave one live render', () => {
  const slot = new RenderSlot();
  const first = slot.claim();            // initial page render

  slot.invalidate(); slot.release();     // click 1
  const second = slot.claim();
  slot.invalidate(); slot.release();     // click 2, before either finished
  const third = slot.claim();

  slot.finish(first);                    // the old renders settle late
  slot.finish(second);
  assert.equal(slot.free, false, 'the newest render still owns the slot');
  assert.equal(slot.canAttach(first), false);
  assert.equal(slot.canAttach(second), false);
  assert.equal(slot.canAttach(third), true, 'only the newest may attach');

  slot.finish(third);
  assert.equal(slot.free, true);
});

test('sibling pages render independently but invalidate together', () => {
  // One shared slot for the whole document would mean only one page ever
  // renders: the others claim nothing and are never retried.
  const shared = new Generation();
  const one = new RenderSlot(shared);
  const two = new RenderSlot(shared);

  const a = one.claim();
  assert.equal(two.free, true, 'page two can render while page one is busy');
  const b = two.claim();

  shared.bump();                        // a zoom
  assert.equal(one.canAttach(a), false);
  assert.equal(two.canAttach(b), false);
});

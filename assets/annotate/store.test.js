import test from 'node:test';
import assert from 'node:assert/strict';
import { InkStore, twinSurface } from './store.js';

const stroke = (d) => ({ tool: 'pen', d, color: '#000' });

test('strokes are kept per page', () => {
  const s = new InkStore();
  s.add(1, stroke('a'));
  s.add(2, stroke('b'));
  assert.equal(s.get(1).length, 1);
  assert.equal(s.get(2).length, 1);
});

test('undo crosses pages in the order the marks were made', () => {
  const s = new InkStore();
  s.add(2, stroke('first'));
  s.add(3, stroke('second'));
  s.undo();
  assert.equal(s.get(3).length, 0);
  assert.equal(s.get(2).length, 1);
  s.undo();
  assert.equal(s.get(2).length, 0);
});

test('redo restores what undo took', () => {
  const s = new InkStore();
  s.add(1, stroke('a'));
  s.undo();
  s.redo();
  assert.equal(s.get(1).length, 1);
});

test('a new mark clears the redo stack', () => {
  const s = new InkStore();
  s.add(1, stroke('a'));
  s.undo();
  s.add(1, stroke('b'));
  assert.equal(s.redo(), false);
  assert.equal(s.get(1)[0].d, 'b');
});

test('undo on an empty history is a no-op, not a crash', () => {
  assert.equal(new InkStore().undo(), false);
});

test('erasing removes the named strokes only', () => {
  const s = new InkStore();
  s.add(1, stroke('a')); s.add(1, stroke('b')); s.add(1, stroke('c'));
  s.removeAt(1, [0, 2]);
  assert.deepEqual(s.get(1).map((x) => x.d), ['b']);
});

test('serialising drops pages that hold nothing', () => {
  const s = new InkStore();
  s.add(1, stroke('a'));
  s.add(2, stroke('b'));
  s.clearPage(2);
  assert.deepEqual(Object.keys(s.toJSON()), ['1']);
});

test('it reports emptiness so an untouched page saves nothing', () => {
  const s = new InkStore();
  assert.equal(s.isEmpty, true);
  s.add(1, stroke('a'));
  assert.equal(s.isEmpty, false);
});

test('history is bounded so a long session cannot grow without limit', () => {
  const s = new InkStore();
  for (let i = 0; i < 80; i += 1) s.add(1, stroke(`s${i}`));
  assert.ok(s.past.length <= 50);
});

test('an existing layer loads as the starting state', () => {
  const s = new InkStore({ 4: [stroke('old')] });
  assert.equal(s.get(4).length, 1);
});

test('the margin is a separate surface from the page', () => {
  const s = new InkStore();
  s.add(1, stroke('page'));
  s.add(1, stroke('margin'), 'pad');
  assert.equal(s.get(1).length, 1);
  assert.equal(s.get(1, 'pad').length, 1);
  assert.equal(s.get(1)[0].d, 'page');
  assert.equal(s.get(1, 'pad')[0].d, 'margin');
});

test('undo crosses the two surfaces in the order they were drawn', () => {
  const s = new InkStore();
  s.add(1, stroke('page'));
  s.add(1, stroke('margin'), 'pad');
  s.undo();
  assert.equal(s.get(1, 'pad').length, 0);
  assert.equal(s.get(1).length, 1);
});

test('each surface serialises on its own', () => {
  const s = new InkStore();
  s.add(2, stroke('page'));
  s.add(3, stroke('margin'), 'pad');
  assert.deepEqual(Object.keys(s.toJSON()), ['2']);
  assert.deepEqual(Object.keys(s.padsToJSON()), ['3']);
});

test('a margin note alone counts as not empty', () => {
  const s = new InkStore();
  s.add(1, stroke('margin'), 'pad');
  assert.equal(s.isEmpty, false);
});

test('existing margin notes load as the starting state', () => {
  const s = new InkStore({ 1: [stroke('p')] }, { pads: { 1: [stroke('m')] } });
  assert.equal(s.get(1).length, 1);
  assert.equal(s.get(1, 'pad').length, 1);
  assert.equal(s.padUsed(1), true);
  assert.equal(s.padUsed(2), false);
});

test('erasing in the margin leaves the page alone', () => {
  const s = new InkStore();
  s.add(1, stroke('page'));
  s.add(1, stroke('margin'), 'pad');
  s.removeAt(1, [0], 'pad');
  assert.equal(s.get(1, 'pad').length, 0);
  assert.equal(s.get(1).length, 1);
});

// ---- the translation beside the English (task #825) ---------------------

test('ink on a translation is its own surface, per language', () => {
  const s = new InkStore({}, { twins: { de: { 2: [stroke('old')] } } });
  s.add(2, stroke('new'), twinSurface('de'));
  s.add(1, stroke('zh'), twinSurface('zh'));
  assert.deepEqual(s.get(2, twinSurface('de')).map((x) => x.d), ['old', 'new']);
  assert.equal(s.get(2).length, 0, 'not on the English page');
  assert.deepEqual(s.twinsToJSON(), { de: { 2: [stroke('old'), stroke('new')] },
                                      zh: { 1: [stroke('zh')] } });
});

test('undo crosses from the translation to the English', () => {
  const s = new InkStore();
  s.add(1, stroke('english'));
  s.add(1, stroke('deutsch'), twinSurface('de'));
  s.undo();
  assert.equal(s.get(1, twinSurface('de')).length, 0);
  assert.equal(s.get(1).length, 1);
});

test('a language whose ink was all erased is sent as gone', () => {
  // the server replaces twins with what is sent, so an emptied language must
  // not linger in it; and one never drawn on adds nothing
  const s = new InkStore({}, { twins: { de: { 1: [stroke('a')] } } });
  s.removeAt(1, [0], twinSurface('de'));
  assert.deepEqual(s.twinsToJSON(), {});
  assert.equal(s.isEmpty, true);
});

test('languages loaded but not shown are kept', () => {
  const s = new InkStore({}, { twins: { zh: { 3: [stroke('z')] } } });
  s.add(1, stroke('d'), twinSurface('de'));
  assert.deepEqual(Object.keys(s.twinsToJSON()).sort(), ['de', 'zh']);
});

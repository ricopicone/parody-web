import { strict as assert } from 'node:assert';
import { test } from 'node:test';
import { Highlight } from './highlight.js';
import { BlankMarks } from './blanks.js';

/**
 * Assigning `canvas.width` RESETS the drawing surface — it reallocates and
 * zeroes the whole backing store, even when the value assigned is the one it
 * already had. Both layers re-fit on every animation frame (the page may have
 * been zoomed) and on every scroll event, so an unconditional fit meant a
 * 1620x2430 buffer thrown away and rebuilt 60 times a second at dpr 3.
 *
 * Counted rather than timed: the wasted work is the same on every machine,
 * while wall clock is not, and a hidden tab does not paint at all.
 */
function stubDom(width = 540, height = 810) {
  const counts = { widthSets: 0, heightSets: 0, contexts: 0, fills: 0,
                   clears: 0 };
  const ctx = {
    setTransform() {}, clearRect() { counts.clears += 1; },
    fillRect() { counts.fills += 1; }, strokeRect() {}, fillStyle: '',
    strokeStyle: '', lineWidth: 0,
  };
  const canvas = {
    className: '', style: {}, remove() {},
    getContext() { counts.contexts += 1; return ctx; },
    _w: 0, _h: 0,
    get width() { return this._w; },
    set width(v) { counts.widthSets += 1; this._w = v; },
    get height() { return this._h; },
    set height(v) { counts.heightSets += 1; this._h = v; },
  };
  global.document = { createElement: () => canvas };
  global.window = { devicePixelRatio: 3 };
  const page = { el: { offsetWidth: width, offsetHeight: height,
                       appendChild() {} }, scale: 1 };
  return { counts, page };
}

test('re-fitting at the same size does not rebuild the canvas', () => {
  const { counts, page } = stubDom();
  const layer = new Highlight(page);
  const after = counts.widthSets;
  for (let i = 0; i < 60; i += 1) layer.fit(page);
  assert.equal(counts.widthSets, after, 'the backing store was reallocated');
  assert.equal(counts.contexts, 1, 'the context was re-acquired');
});

test('a real size change does rebuild it', () => {
  const { counts, page } = stubDom();
  const layer = new Highlight(page);
  const before = counts.widthSets;
  layer.fit({ ...page, el: { ...page.el, offsetWidth: 800 } });
  assert.equal(counts.widthSets, before + 1, 'zoom must re-fit');
});

test('showing the same box again does not repaint', () => {
  const { counts, page } = stubDom();
  const layer = new Highlight(page);
  layer.show([1, 2, 3, 4]);
  const fills = counts.fills;
  for (let i = 0; i < 60; i += 1) layer.show([1, 2, 3, 4]);
  assert.equal(counts.fills, fills, 'the mark had not moved');
});

test('the mark still follows the voice to a new word', () => {
  const { counts, page } = stubDom();
  const layer = new Highlight(page);
  layer.show([1, 2, 3, 4]);
  const fills = counts.fills;
  layer.show([5, 6, 7, 8]);
  assert.equal(counts.fills, fills + 1);
});

test('blank markers do not rebuild their canvas per scroll event', () => {
  const { counts, page } = stubDom();
  const marks = new BlankMarks(page);
  marks.setBoxes([{ token: 1, x0: 1, y0: 2, x1: 3, y1: 4 }]);
  const after = counts.widthSets;
  for (let i = 0; i < 60; i += 1) marks.fit(page);
  assert.equal(counts.widthSets, after);
});

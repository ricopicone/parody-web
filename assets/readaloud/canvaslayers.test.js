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

test('re-placing the same reveal does not rebuild its picture', async () => {
  const { Reveal } = await import('./reveal.js');
  let htmlWrites = 0;
  const el = {
    style: {}, dataset: {}, hidden: true, classList: { add() {}, remove() {} },
    offsetWidth: 100, offsetHeight: 40, parentElement: null,
    remove() {}, appendChild() {}, addEventListener() {},
    set innerHTML(v) { htmlWrites += 1; this._h = v; },
    get innerHTML() { return this._h; },
    set textContent(v) { htmlWrites += 1; },
    get textContent() { return ''; },
  };
  global.document = { createElement: () => el };
  const page = { el: { offsetWidth: 540, offsetHeight: 810,
                       appendChild() { el.parentElement = page.el; } },
                 scale: 1, pad: null };
  const reveal = new Reveal();
  const cloze = { kind: 'cloze', svg: '<svg>a very large picture</svg>',
                  x0: 1, y0: 2, x1: 3, y1: 4 };
  reveal.show(cloze, page, 12);
  const after = htmlWrites;
  // The marker sync re-places it on every scroll event.
  for (let i = 0; i < 60; i += 1) reveal.show(cloze, page, 12);
  assert.equal(htmlWrites, after, 'the SVG was re-parsed');
});

test('a different reveal does rebuild', async () => {
  const { Reveal } = await import('./reveal.js');
  let htmlWrites = 0;
  const el = {
    style: {}, dataset: {}, hidden: true, classList: { add() {}, remove() {} },
    offsetWidth: 100, offsetHeight: 40, parentElement: null,
    remove() {}, appendChild() {}, addEventListener() {},
    set innerHTML(v) { htmlWrites += 1; }, get innerHTML() { return ''; },
    set textContent(v) { htmlWrites += 1; }, get textContent() { return ''; },
  };
  global.document = { createElement: () => el };
  const page = { el: { offsetWidth: 540, offsetHeight: 810,
                       appendChild() {} }, scale: 1, pad: null };
  const reveal = new Reveal();
  reveal.show({ kind: 'cloze', answer: 'one', x0: 1, y0: 2, x1: 3, y1: 4 },
              page, 12);
  const after = htmlWrites;
  reveal.show({ kind: 'cloze', answer: 'two', x0: 1, y0: 2, x1: 3, y1: 4 },
              page, 12);
  assert.equal(htmlWrites, after + 1);
});

test('marker layers do not redraw when nothing became active', () => {
  const { counts, page } = stubDom();
  const marks = new BlankMarks(page);
  marks.setBoxes([{ token: 1, x0: 1, y0: 2, x1: 3, y1: 4 }]);
  marks.setActive(1);
  const fills = counts.fills;
  for (let i = 0; i < 60; i += 1) marks.setActive(1);
  assert.equal(counts.fills, fills, 'the same blank was already active');
  marks.setActive(2);
  assert.ok(counts.fills > fills, 'a new active blank must redraw');
});

test('an equation being read shows progress, and still costs almost nothing', () => {
  // One equation is one token with one box, and the voice can be inside it for
  // a minute — so the mark has to move without the word changing. It must not
  // undo the frame-loop work: progress is quantised to whole pixels, so most
  // frames decide to do nothing.
  const { counts, page } = stubDom();
  const layer = new Highlight(page);
  const box = [0, 0, 100, 12];              // a one-line equation, 100pt wide
  let painted = 0;
  const before = counts.fills;
  // 600 frames across ten seconds of narration
  for (let i = 0; i < 600; i += 1) layer.showProgress(box, i / 600);
  painted = counts.fills - before;
  assert.ok(painted > 0, 'the mark must move');
  // 100 CSS px of travel: at most one repaint per pixel, each drawing the
  // faint whole-equation wash plus the filled part.
  assert.ok(painted <= 100 * 2 + 2,
            `repainted ${painted} times for 100px of travel`);
  assert.equal(counts.widthSets, 1, 'the canvas must not be rebuilt');
});

test('progress fills downwards for a derivation and rightwards for one line', () => {
  const { page } = stubDom();
  const layer = new Highlight(page);
  const rects = [];
  layer.ctx.fillRect = (x, y, w, h) => rects.push([x, y, w, h]);
  layer.showProgress([0, 0, 100, 12], 0.5);        // one line
  const wide = rects.pop();
  rects.length = 0;
  layer.showProgress([0, 0, 100, 200], 0.5);       // a tall derivation
  const tall = rects.pop();
  assert.ok(wide[2] < 100, 'a single line fills rightwards');
  assert.ok(tall[3] < 200 && tall[2] > 100, 'a derivation fills downwards');
});

test('leaving the equation returns to an ordinary mark', () => {
  const { counts, page } = stubDom();
  const layer = new Highlight(page);
  layer.showProgress([0, 0, 100, 12], 0.5);
  const fills = counts.fills;
  layer.show([0, 0, 100, 12]);
  assert.ok(counts.fills > fills, 'the plain mark must repaint over the band');
});

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

/**
 * Enough of an element to see what the marks build.
 *
 * Hand-rolled rather than a DOM library, like the other tests here: what is
 * being asserted is the SHAPE of what gets built, and a fake makes the one
 * thing that matters — that no canvas is ever asked for — checkable.
 */
function stubDom({ offsetWidth = 540, offsetHeight = 810, scale = 1 } = {}) {
  const made = [];
  const el = (tag) => {
    const node = {
      tag, className: '', dataset: {}, style: {}, children: [],
      parentElement: null,
      appendChild(child) {
        this.children.push(child); child.parentElement = this; return child;
      },
      replaceChildren() {
        for (const c of this.children) c.parentElement = null;
        this.children = [];
      },
      remove() {
        const p = this.parentElement;
        if (p) p.children.splice(p.children.indexOf(this), 1);
        this.parentElement = null;
      },
    };
    made.push(node);
    return node;
  };
  global.document = { createElement: el };
  global.window = { devicePixelRatio: 3 };
  const page = { el: { ...el('div'), offsetWidth, offsetHeight }, scale };
  return { made, page, canvases: () => made.filter((n) => n.tag === 'canvas') };
}

const blanksIn = (marks) =>
  marks.host.children.filter((c) => c.className === 'readalong-blank');

test('the marks cost no canvas at all', () => {
  // The defect: a FULL-PAGE canvas per page — 7 MB at dpr 2, 16 MB at dpr 3 —
  // for a handful of small rectangles. And not a window of them: syncMarks
  // wants every page in the section that has a blank, and every page element
  // exists from the start, so they were all allocated at once. Measured at
  // 20 MB of 33 MB on a three-page section.
  const { page, canvases } = stubDom();
  const marks = new BlankMarks(page);
  marks.setBoxes([{ token: 1, x0: 10, y0: 20, x1: 90, y1: 30 },
                  { token: 2, x0: 10, y0: 40, x1: 90, y1: 50 }]);
  assert.equal(canvases().length, 0, 'no canvas may be allocated');
});

test('one element per blank, and no more', () => {
  const { page } = stubDom();
  const marks = new BlankMarks(page);
  marks.setBoxes([{ token: 1, x0: 10, y0: 20, x1: 90, y1: 30 },
                  { token: 2, x0: 10, y0: 40, x1: 90, y1: 50 }]);
  assert.equal(blanksIn(marks).length, 2);

  marks.setBoxes([{ token: 3, x0: 1, y0: 2, x1: 3, y1: 4 }]);
  assert.equal(blanksIn(marks).length, 1, 'the old ones are not left behind');
});

test('a clozed equation is outlined, not washed over', () => {
  // Its box is the whole derivation. A fill there is a slab of colour across
  // the maths; a one-line blank is a space to write in and keeps its wash.
  const { page } = stubDom();
  const marks = new BlankMarks(page);
  marks.setBoxes([{ token: 1, kind: 'math_cloze', x0: 1, y0: 2, x1: 90, y1: 80 },
                  { token: 2, kind: 'cloze', x0: 1, y0: 90, x1: 40, y1: 92 }]);
  const [equation, ordinary] = blanksIn(marks);
  assert.equal(equation.dataset.kind, 'math_cloze');
  assert.equal(ordinary.dataset.kind, 'cloze');
});

test('blanks are placed in percentages, so a zoom moves them for free', () => {
  // The canvas had to be reallocated and every mark repainted on a zoom. A
  // percentage of the page box is the same number at every scale.
  const { page } = stubDom({ offsetWidth: 540, scale: 1.5 });   // 360pt wide
  const marks = new BlankMarks(page);
  marks.setBoxes([{ token: 1, x0: 36, y0: 54, x1: 72, y1: 81 }]);
  const [node] = blanksIn(marks);
  assert.equal(node.style.left, '10%');
  assert.equal(node.style.width, '10%');

  const before = { ...node.style };
  marks.fit({ ...page, el: { ...page.el, offsetWidth: 1080 }, scale: 3 });
  assert.deepEqual({ ...node.style }, before, 'nothing was recomputed');
});

test('a box given backwards is still placed the right way round', () => {
  const { page } = stubDom({ offsetWidth: 100, scale: 1 });
  const marks = new BlankMarks(page);
  marks.setBoxes([{ token: 1, x0: 40, y0: 30, x1: 10, y1: 20 }]);
  const [node] = blanksIn(marks);
  assert.equal(node.style.left, '10%');
  assert.equal(node.style.width, '30%');
});

test('moving the active blank flips flags rather than rebuilding', () => {
  const { page } = stubDom();
  const marks = new BlankMarks(page);
  marks.setBoxes([{ token: 1, x0: 1, y0: 2, x1: 3, y1: 4 },
                  { token: 2, x0: 1, y0: 5, x1: 3, y1: 6 }]);
  const nodes = blanksIn(marks);

  marks.setActive(2);
  assert.deepEqual(nodes.map((n) => n.dataset.on), ['0', '1']);
  assert.equal(blanksIn(marks)[0], nodes[0], 'the same elements, moved');

  marks.setActive(1);
  assert.deepEqual(nodes.map((n) => n.dataset.on), ['1', '0']);
});

test('the theme is one attribute, not a repaint of every blank', () => {
  const { page } = stubDom();
  const marks = new BlankMarks(page);
  marks.setBoxes([{ token: 1, x0: 1, y0: 2, x1: 3, y1: 4 }]);
  const [node] = blanksIn(marks);

  marks.setDark(true);
  assert.equal(marks.host.dataset.dark, '1');
  assert.equal(node.dataset.on, '0', 'the blanks themselves did not change');
});

test('a page with no size yet is placed when it gets one', () => {
  // syncMarks runs as soon as the page ELEMENT exists, which is the point —
  // the reader looks for blanks before anything has rasterised.
  const { page } = stubDom({ offsetWidth: 0, offsetHeight: 0 });
  const marks = new BlankMarks(page);
  marks.setBoxes([{ token: 1, x0: 10, y0: 20, x1: 90, y1: 30 }]);
  assert.equal(blanksIn(marks)[0].style.left, undefined, 'nothing to place against');

  marks.fit({ ...page, el: { ...page.el, offsetWidth: 100, offsetHeight: 100 } });
  assert.equal(blanksIn(marks)[0].style.left, '10%');
});

test('destroying takes the whole layer off the page', () => {
  const { page } = stubDom();
  const marks = new BlankMarks(page);
  marks.setBoxes([{ token: 1, x0: 1, y0: 2, x1: 3, y1: 4 }]);
  assert.equal(page.el.children.length, 1);
  marks.destroy();
  assert.equal(page.el.children.length, 0);
});

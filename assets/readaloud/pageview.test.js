import { strict as assert } from 'node:assert';
import { test } from 'node:test';
import { isRendered, pageAt } from './pageview.js';

/**
 * A DOM stub. Only what pageview.js touches, so the test needs no jsdom —
 * matching how assets/annotate/*.test.js stays dependency-free.
 */
function makeRoot(pages) {
  const nodes = pages.map(({ number, width, canvas }) => {
    const pad = { className: 'ink-pad' };
    const el = {
      className: 'ink-page',
      dataset: { page: String(number) },
      offsetWidth: width,
      style: { width: `${width}px` },
      querySelector: (sel) => (sel.includes('canvas') && canvas ? {} : null),
    };
    el.parentElement = {
      querySelector: (sel) => (sel === '.ink-pad' ? pad : null),
    };
    return { number, el, pad };
  });
  return {
    querySelector: (sel) => {
      const match = /data-page="(\d+)"/.exec(sel);
      const found = nodes.find((n) => String(n.number) === match[1]);
      return found ? found.el : null;
    },
  };
}

const SIZES = [[200, 100], [200, 100]];

test('derives the scale from the rendered width', () => {
  const root = makeRoot([{ number: 1, width: 400, canvas: true }]);
  assert.equal(pageAt(root, 0, SIZES).scale, 2);
});

test('page numbers in the DOM are one-based', () => {
  const root = makeRoot([{ number: 2, width: 200, canvas: true }]);
  assert.equal(pageAt(root, 0, SIZES), null);
  assert.ok(pageAt(root, 1, SIZES));
});

test('a page the viewer has not laid out yet is a miss, not a crash', () => {
  const root = makeRoot([]);
  assert.equal(pageAt(root, 0, SIZES), null);
});

test('a page with no size in the payload is a miss', () => {
  const root = makeRoot([{ number: 1, width: 400, canvas: true }]);
  assert.equal(pageAt(root, 0, []), null);
});

test('the margin pad is found alongside the page', () => {
  const root = makeRoot([{ number: 1, width: 400, canvas: true }]);
  assert.equal(pageAt(root, 0, SIZES).pad.className, 'ink-pad');
});

test('a placeholder without a canvas is not rendered', () => {
  const root = makeRoot([{ number: 1, width: 400, canvas: false }]);
  assert.equal(isRendered(pageAt(root, 0, SIZES)), false);
});

test('a page holding a canvas is rendered', () => {
  const root = makeRoot([{ number: 1, width: 400, canvas: true }]);
  assert.equal(isRendered(pageAt(root, 0, SIZES)), true);
});

test('isRendered copes with a missing page', () => {
  assert.equal(isRendered(null), false);
});

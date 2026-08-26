import test from 'node:test';
import assert from 'node:assert/strict';
import { LayerSet } from './layers.js';

/** A stand-in for InkLayer that records whether it was destroyed. */
class FakeLayer {
  constructor(surface) { this.surface = surface; this.destroyed = 0; this.resized = 0; }
  destroy() { this.destroyed += 1; }
  resize() { this.resized += 1; }
}

const entry = (number) => ({ number, viewport: { width: 540, height: 810 } });

function set() {
  const built = [];
  const layers = new LayerSet((e) => {
    const pair = { page: new FakeLayer('page'), pad: new FakeLayer('pad') };
    built.push({ number: e.number, pair });
    return pair;
  });
  return { layers, built };
}

/** Every layer this set has ever built, over the whole run. */
const alive = (built) =>
  built.filter(({ pair }) => !pair.page.destroyed || !pair.pad.destroyed).length;

test('a page that goes away releases both of its surfaces', () => {
  // The defect: index.js passed only onPageReady, so `layers` never shrank and
  // two Konva stages per page — ~59 MB on a six-page section — stayed alive
  // for the life of the tab.
  const { layers, built } = set();
  layers.ensure(entry(1));
  assert.equal(layers.size, 1);

  layers.release(1);
  assert.equal(layers.size, 0);
  assert.equal(built[0].pair.page.destroyed, 1, 'the page layer');
  assert.equal(built[0].pair.pad.destroyed, 1, 'the margin pad too');
});

test('scrolling through a section leaves nothing behind', () => {
  // The measurement that opened the task: scroll once through six pages and
  // twelve stages are still alive. Only pages near the viewport hold layers.
  const { layers, built } = set();
  const WINDOW = 3;
  for (let page = 1; page <= 6; page += 1) {
    layers.ensure(entry(page));
    if (page > WINDOW) layers.release(page - WINDOW);
  }
  assert.equal(layers.size, WINDOW, 'only the window is resident');

  for (let page = 4; page <= 6; page += 1) layers.release(page);
  assert.equal(layers.size, 0);
  assert.equal(alive(built), 0, 'every layer built was destroyed');
});

test('a page that comes back is built fresh rather than stacked', () => {
  const { layers, built } = set();
  layers.ensure(entry(2));
  layers.release(2);
  layers.ensure(entry(2));

  assert.equal(layers.size, 1);
  assert.equal(built.length, 2, 'the second visit built a new pair');
  assert.notEqual(built[0].pair, built[1].pair);
  assert.equal(built[1].pair.page.destroyed, 0, 'and the new one is live');
});

test('a page already resident is not built twice', () => {
  // onPageReady announcing the same page again must not orphan the layers the
  // reader is drawing on — that would leak them AND lose the live strokes.
  const { layers, built } = set();
  const first = layers.ensure(entry(3));
  const second = layers.ensure(entry(3));

  assert.equal(built.length, 1);
  assert.equal(first.pair, second.pair);
  assert.equal(first.built, true);
  assert.equal(second.built, false, 'the caller can tell it was already there');
});

test('releasing a page that holds no layers is a no-op', () => {
  // _release() runs on every page outside the window on every scroll frame.
  const { layers } = set();
  assert.equal(layers.release(9), false);
  assert.equal(layers.size, 0);
});

test('releasing twice destroys once', () => {
  const { layers, built } = set();
  layers.ensure(entry(1));
  assert.equal(layers.release(1), true);
  assert.equal(layers.release(1), false);
  assert.equal(built[0].pair.page.destroyed, 1);
});

test('releaseAll empties the set', () => {
  const { layers, built } = set();
  for (const page of [1, 2, 3]) layers.ensure(entry(page));
  layers.releaseAll();
  assert.equal(layers.size, 0);
  assert.equal(alive(built), 0);
});

test('forEach visits each resident page with its number', () => {
  // store.onChange uses this to mark a margin that has just gained its first
  // mark; a released page must not be visited, because its layers are gone.
  const { layers } = set();
  layers.ensure(entry(1));
  layers.ensure(entry(2));
  layers.release(1);

  const seen = [];
  layers.forEach((pair, number) => seen.push(number));
  assert.deepEqual(seen, [2]);
});

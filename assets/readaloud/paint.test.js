import { strict as assert } from 'node:assert';
import { test } from 'node:test';
import { paintWord } from './paint.js';
import { MarkState } from './mark.js';

const WORD = { page: 3, x0: 10, y0: 20, x1: 40, y1: 32, token: 7 };

/** A page element exists, and has its true size, whether or not it has been
 *  rasterised — that is how the viewer lays a document out. */
function harness({ rendered = true } = {}) {
  const log = { followed: [], drew: [] };
  const page = { el: {}, scale: 1.5 };
  return {
    log,
    page,
    run: (word = WORD, index = 1, opts = {}) => paintWord(word, index, {
      mark: opts.mark || harness.mark,
      inEquation: opts.inEquation || false,
      findPage: () => page,
      findLayer: () => (rendered ? { page } : null),
      follow: (p, w) => log.followed.push(w.page),
      draw: (layer, w) => log.drew.push(w.page),
      ...opts,
    }),
  };
}

test('the page follows the voice onto a page that has NOT rendered yet', () => {
  // THE DEADLOCK. follow() used to sit below the layer check, so the page
  // could only be told to travel to a word that was already drawn — and a
  // word is only drawn on a rasterised page, and a page is only rasterised
  // near the viewport. Once the voice left the rendered window the page
  // stopped following it, so it never rendered, so the mark never came back.
  // Measured on robotics.ricopic.one: walking the voice through all 487 words
  // of a section produced TWO scroll requests, and none at all for any page
  // that had not already rendered.
  const h = harness({ rendered: false });
  const mark = new MarkState();
  const status = h.run(WORD, 1, { mark });

  assert.equal(status, 'unrendered');
  assert.deepEqual(h.log.followed, [3], 'it must still travel there');
  assert.deepEqual(h.log.drew, [], 'there is nothing to draw on yet');
});

test('a word it could not draw is still owed, so the next frame retries', () => {
  const h = harness({ rendered: false });
  const mark = new MarkState();
  h.run(WORD, 1, { mark });
  assert.equal(mark.needs(1), true);
});

test('a rendered page both follows and draws', () => {
  const h = harness({ rendered: true });
  const mark = new MarkState();
  assert.equal(h.run(WORD, 1, { mark }), 'painted');
  assert.deepEqual(h.log.followed, [3]);
  assert.deepEqual(h.log.drew, [3]);
  assert.equal(mark.needs(1), false, 'and is remembered');
});

test('an unchanged word does nothing at all — not even a follow', () => {
  // The frame loop runs sixty times a second; re-asking to scroll on every
  // frame is what made the smooth scroll crawl and never arrive.
  const h = harness({ rendered: true });
  const mark = new MarkState();
  h.run(WORD, 1, { mark });
  h.log.followed.length = 0;
  assert.equal(h.run(WORD, 1, { mark }), 'unchanged');
  assert.deepEqual(h.log.followed, []);
});

test('a word with no box anywhere neither follows nor draws', () => {
  const h = harness({ rendered: true });
  const mark = new MarkState();
  const nowhere = { page: undefined, token: 1 };
  assert.equal(h.run(nowhere, 4, { mark }), 'no-box');
  assert.deepEqual(h.log.followed, []);
  assert.deepEqual(h.log.drew, []);
  assert.equal(mark.needs(4), false, 'and never asked about again');
});

test('an equation keeps drawing and keeps following while it is read', () => {
  const h = harness({ rendered: true });
  const mark = new MarkState();
  h.run(WORD, 1, { mark, inEquation: true });
  h.run(WORD, 1, { mark, inEquation: true });
  assert.equal(h.log.drew.length, 2, 'the mark moves through it');
});

test('a page the viewer has not laid out yet is not followed to', () => {
  // pageAt returns null before the element exists; there is nowhere to go.
  const log = [];
  const mark = new MarkState();
  const status = paintWord(WORD, 1, {
    mark,
    findPage: () => null,
    findLayer: () => null,
    follow: () => log.push('followed'),
    draw: () => {},
  });
  assert.equal(status, 'unrendered');
  assert.deepEqual(log, []);
});

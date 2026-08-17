import test from 'node:test';
import assert from 'node:assert/strict';
import { _body } from './api.js';

const state = { sliceKey: 'k', bookSha: 'b', pages: [1, 4],
                strokes: { 1: [{ d: 'A' }] }, pads: { 1: [{ d: 'M' }] } };

test('the margin is sent, not silently dropped', () => {
  // It was: the payload carried pads and save() rebuilt the body from an
  // explicit field list that did not mention them, so every margin note was
  // saved as nothing.
  assert.deepEqual(_body(state).pads, { 1: [{ d: 'M' }] });
});

test('the page strokes are sent too', () => {
  assert.deepEqual(_body(state).strokes, { 1: [{ d: 'A' }] });
});

test('the version and page range travel with them', () => {
  const body = _body(state);
  assert.equal(body.slice_key, 'k');
  assert.equal(body.book_sha256, 'b');
  assert.deepEqual(body.pages, [1, 4]);
});

test('missing surfaces become empty objects rather than undefined', () => {
  const body = _body({ sliceKey: 'k' });
  assert.deepEqual(body.strokes, {});
  assert.deepEqual(body.pads, {});
});

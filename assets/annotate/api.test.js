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


/* ---- save(), including the compressed path ------------------------------ */

import { InkApi } from './api.js';

/** Minimal browser furniture: save() reads the CSRF cookie. */
function withDom(fn) {
  const had = 'document' in globalThis;
  globalThis.document = { cookie: 'csrftoken=abc123' };
  return (async () => { try { return await fn(); } finally {
    if (!had) delete globalThis.document;
  } })();
}

/** A CompressionStream that really gzips, via the platform's own. */
const REAL_CS = globalThis.CompressionStream;

const bigState = () => ({
  sliceKey: 'k', bookSha: 'b', pages: [1, 2],
  strokes: { 1: Array.from({ length: 400 }, () => ({ d: 'M 1 2 ' + 'L 3 4 '.repeat(40) })) },
  pads: {},
});

test('a big save goes out gzipped', async () => {
  await withDom(async () => {
    const seen = [];
    globalThis.fetch = async (url, init) => { seen.push(init); return { ok: true, status: 200 }; };
    const api = new InkApi('/one/alpha/');
    assert.equal(await api.save(bigState()), true);
    assert.equal(seen.length, 1);
    assert.equal(seen[0].headers['Content-Encoding'], 'gzip');
  });
});

test('a small save goes out as plain JSON', async () => {
  await withDom(async () => {
    const seen = [];
    globalThis.fetch = async (url, init) => { seen.push(init); return { ok: true, status: 200 }; };
    const api = new InkApi('/one/alpha/');
    await api.save({ sliceKey: 'k', strokes: {}, pads: {} });
    assert.equal(seen[0].headers['Content-Encoding'], undefined);
    assert.equal(typeof seen[0].body, 'string');
  });
});

test('a proxy that mangles gzip costs one save, not the session', async () => {
  // The failure this guards against is real: a gzipped REQUEST crosses
  // Cloudflare and nginx before Django reads it. If it arrives broken the
  // reader must land on plain bytes immediately, not lose their ink (#667).
  await withDom(async () => {
    const seen = [];
    globalThis.fetch = async (url, init) => {
      seen.push(init);
      const gz = init.headers['Content-Encoding'] === 'gzip';
      return { ok: !gz, status: gz ? 400 : 200 };
    };
    const api = new InkApi('/one/alpha/');
    assert.equal(await api.save(bigState()), true);   // retried, and landed
    assert.equal(seen.length, 2);
    assert.equal(seen[0].headers['Content-Encoding'], 'gzip');
    assert.equal(seen[1].headers['Content-Encoding'], undefined);

    // and it does not try gzip again for the rest of the session
    await api.save(bigState());
    assert.equal(seen.length, 3);
    assert.equal(seen[2].headers['Content-Encoding'], undefined);
  });
});

test('too much ink is not treated as an encoding problem', async () => {
  // 413 says the section is enormous, not that gzip is broken. Turning
  // compression off there would make the next attempt three times bigger.
  await withDom(async () => {
    const seen = [];
    globalThis.fetch = async (url, init) => { seen.push(init); return { ok: false, status: 413 }; };
    const api = new InkApi('/one/alpha/');
    assert.equal(await api.save(bigState()), false);
    assert.equal(seen.length, 1);                  // no pointless retry
    assert.equal(api.downgrade.off, false);
  });
});

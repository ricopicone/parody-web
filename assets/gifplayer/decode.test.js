import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { parseGif } from './decode.js';

const FIX = new URL('./fixtures/', import.meta.url);
const EXPECTED = JSON.parse(readFileSync(new URL('expected.json', FIX), 'utf8'));
const load = (name) => new Uint8Array(readFileSync(new URL(name, FIX)));

// browsers play a 0 or 10 ms frame at 100 ms; the player does as they do
const played = (ms) => (ms < 20 ? 100 : ms);

test('every fixture is listed in expected.json', () => {
  const gifs = readdirSync(FIX).filter((f) => f.endsWith('.gif')).sort();
  assert.deepEqual(gifs, Object.keys(EXPECTED).sort());
});

for (const [name, want] of Object.entries(EXPECTED)) {
  test(`${name}: size, loop, frame count and delays`, () => {
    const gif = parseGif(load(name));
    assert.equal(gif.width, want.width);
    assert.equal(gif.height, want.height);
    assert.equal(gif.loop, want.loop);
    assert.equal(gif.frames.length, want.frames.length);
    assert.deepEqual(gif.frames.map((f) => f.delay), want.delays.map(played));
  });
}

test('a frame under 20 ms plays at 100 ms', () => {
  assert.deepEqual(parseGif(load('fast.gif')).frames.map((f) => f.delay),
    [100, 100, 100, 100]);
});

test('no NETSCAPE block means the GIF plays once', () => {
  assert.equal(parseGif(load('once.gif')).loop, null);
});

test('a frame records its rectangle, disposal, transparency and interlace', () => {
  const [f0, f1, f2] = parseGif(load('offset.gif')).frames;
  assert.deepEqual([f0.x, f0.y, f0.w, f0.h], [2, 2, 8, 6]);
  assert.equal(f1.disposal, 3);
  assert.equal(f2.disposal, 2);
  assert.equal(f0.transparent, 0);
  assert.equal(f0.interlaced, false);
  assert.equal(parseGif(load('interlaced.gif')).frames[0].interlaced, true);
  assert.equal(parseGif(load('interlaced.gif')).frames[0].transparent, null);
});

test('a frame with no local table uses the global one', () => {
  const f = parseGif(load('offset.gif')).frames[0];
  // global palette of offset.gif: transparent black, sand, navy, rust
  assert.deepEqual([...f.palette.subarray(0, 12)],
    [0, 0, 0, 240, 236, 228, 40, 60, 90, 200, 80, 30]);
});

test('a local table, where a frame has one, replaces the global one', () => {
  const gif = parseGif(load('delta.gif'));
  // Pillow writes a local table on every frame after the first
  assert.notEqual(gif.frames[1].palette, gif.frames[0].palette);
});

test('the LZW data is the sub-blocks themselves, not copies', () => {
  const bytes = load('delta.gif');
  const f = parseGif(bytes).frames[0];
  assert.ok(f.minCodeSize >= 2 && f.minCodeSize <= 8);
  assert.ok(f.data.length >= 1);
  for (const block of f.data) assert.equal(block.buffer, bytes.buffer);
});

test('rejects non-GIF and truncated input', () => {
  assert.throws(() => parseGif(new TextEncoder().encode('<!doctype html>')), /not a GIF/);
  const whole = load('delta.gif');
  assert.throws(() => parseGif(whole.subarray(0, whole.length >> 1)), /truncated/);
  assert.throws(() => parseGif(new Uint8Array(0)), /not a GIF/);
});

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

// ---- decoding and compositing ---------------------------------------------

import { createHash } from 'node:crypto';
import { Compositor, decodeIndices } from './decode.js';

// alpha-0 pixels carry no colour; normalise as make_fixtures.py does
function digest(rgba) {
  const b = Uint8Array.from(rgba);
  for (let p = 0; p < b.length; p += 4) if (b[p + 3] === 0) b.fill(0, p, p + 4);
  return createHash('sha256').update(b).digest('hex');
}

// a budget that makes the snapshot interval exactly k for this GIF
const budgetFor = (gif, k) => Math.ceil((gif.frames.length * gif.width * gif.height * 4) / k);

test('decodeIndices returns one palette index per pixel of the frame', () => {
  const gif = parseGif(load('offset.gif'));
  assert.deepEqual([...decodeIndices(gif.frames[1])], [2, 0, 2, 2, 2, 0, 2, 2, 2, 0, 2, 2]);
});

test('an interlaced frame comes back in row order', () => {
  const f = parseGif(load('interlaced.gif')).frames[0];
  const rows = decodeIndices(f);
  for (let r = 0; r < 16; r++) assert.equal(rows[r * 16], 1 + (r % 3), `row ${r}`);
});

for (const [name, want] of Object.entries(EXPECTED)) {
  test(`${name}: every frame, composited in order, is Pillow's`, () => {
    const c = new Compositor(parseGif(load(name)));
    want.frames.forEach((hash, i) => assert.equal(digest(c.frame(i)), hash, `frame ${i}`));
  });
}

for (const [name, want] of Object.entries(EXPECTED)) {
  for (const k of [2, 3]) {
    test(`${name}: random access equals sequential (snapshot every ${k})`, () => {
      const gif = parseGif(load(name));
      const c = new Compositor(gif, { budget: budgetFor(gif, k) });
      assert.equal(c.interval, Math.min(k, gif.frames.length));
      const n = want.frames.length;
      // last, back to the start, middle, the same frame twice, one back
      const order = [n - 1, 1, n - 2, 0, n >> 1, n >> 1, (n >> 1) - 1];
      for (const i of order) assert.equal(digest(c.frame(i)), want.frames[i], `frame ${i}`);
    });
  }
}

test('dropping the snapshots loses nothing but time', () => {
  const name = 'dispose3.gif';
  const gif = parseGif(load(name));
  const c = new Compositor(gif, { budget: budgetFor(gif, 2) });
  c.frame(4);
  c.dropCache();
  for (const i of [3, 4, 1, 2]) {
    assert.equal(digest(c.frame(i)), EXPECTED[name].frames[i], `frame ${i}`);
    c.dropCache();
  }
});

test('the snapshot interval keeps snapshots within the budget', () => {
  const gif = parseGif(load('delta.gif')); // 6 frames of 32x24
  const frameBytes = 32 * 24 * 4;
  assert.equal(new Compositor(gif, { budget: 6 * frameBytes }).interval, 1);
  assert.equal(new Compositor(gif, { budget: 3 * frameBytes }).interval, 2);
  assert.equal(new Compositor(gif, { budget: frameBytes }).interval, 6);
  // never longer than the animation: then only frame 0 is kept
  assert.equal(new Compositor(gif, { budget: 1 }).interval, 6);
  assert.equal(new Compositor(gif).interval, 1); // default 16 MiB
});

test('a frame outside the animation is refused', () => {
  const c = new Compositor(parseGif(load('delta.gif')));
  assert.throws(() => c.frame(6), RangeError);
  assert.throws(() => c.frame(-1), RangeError);
  assert.throws(() => c.frame(1.5), RangeError);
});

test('a first frame with disposal 3 restores to nothing, as browsers do', () => {
  // Pillow keeps such a frame; Chrome restores the empty screen it was drawn
  // over (Blink's FindRequiredPreviousFrame skips restore-previous frames back
  // to "no previous frame"). The player stands in for the browser, so it
  // follows the browser. offset.gif with its first frame patched to disposal 3:
  const bytes = load('offset.gif');
  const gce = bytes.findIndex((b, i) => b === 0x21 && bytes[i + 1] === 0xf9);
  bytes[gce + 3] = (3 << 2) | 1;
  const gif = parseGif(bytes);
  assert.equal(gif.frames[0].disposal, 3);
  const px = new Compositor(gif).frame(1);
  const f1 = gif.frames[1]; // 4x3 at (3,3): navy, hole, navy, navy
  for (let y = 0; y < gif.height; y++) {
    for (let x = 0; x < gif.width; x++) {
      const inside = x >= f1.x && x < f1.x + f1.w && y >= f1.y && y < f1.y + f1.h;
      const navy = inside && (x - f1.x) !== 1;
      assert.equal(px[(y * gif.width + x) * 4 + 3], navy ? 255 : 0, `(${x},${y})`);
    }
  }
});

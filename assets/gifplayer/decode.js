/**
 * A GIF decoder for the figure player: read a GIF's frames, and composite any
 * one of them on demand.
 *
 * Why our own rather than WebCodecs' ImageDecoder: Safari's support for it
 * could not be confirmed, and students read on iPads. This is one code path
 * that every browser runs and `node --test` can check pixel for pixel against
 * Pillow (fixtures/make_fixtures.py).
 *
 * Why compositing matters: a GIF written by Pillow (every animation in the
 * books, via matplotlib) stores only the first frame whole. Each later frame
 * is a rectangle, mostly transparent, drawn over the one before it, so frame k
 * is the sum of frames 0..k and no single frame's pixels are the picture.
 */

/**
 * @typedef {object} Frame
 * @property {number} x
 * @property {number} y
 * @property {number} w
 * @property {number} h
 * @property {number} delay       ms, as browsers play it (under 20 ms → 100)
 * @property {number} disposal    0-3, what happens to this frame's rectangle
 *                                before the next one is drawn
 * @property {number|null} transparent  palette index drawn as "leave it"
 * @property {boolean} interlaced
 * @property {Uint8Array} palette RGB triples (local table, else global)
 * @property {number} minCodeSize
 * @property {Uint8Array[]} data  the LZW sub-blocks, views into the file
 */

/**
 * @typedef {object} Gif
 * @property {number} width
 * @property {number} height
 * @property {number|null} loop  null: no NETSCAPE block, play once
 * @property {Frame[]} frames
 */

/** Read a GIF's structure without decoding any pixels. Throws on a file that
 * is not a GIF or stops before its trailer. */
export function parseGif(bytes) {
  if (bytes.length < 13 || !isGifHeader(bytes)) throw new Error('not a GIF');
  let p = 6;
  const need = (n) => {
    if (p + n > bytes.length) throw new Error('truncated GIF');
  };
  const u16 = (at) => bytes[at] | (bytes[at + 1] << 8);

  const width = u16(p);
  const height = u16(p + 2);
  const screenFlags = bytes[p + 4];
  p += 7;
  let globalPalette = null;
  if (screenFlags & 0x80) {
    const n = 3 * (1 << ((screenFlags & 7) + 1));
    need(n);
    globalPalette = bytes.subarray(p, p + n);
    p += n;
  }

  // the sub-blocks that follow an extension or image: [len][len bytes]... [0]
  const subBlocks = () => {
    const blocks = [];
    for (;;) {
      need(1);
      const len = bytes[p++];
      if (len === 0) return blocks;
      need(len);
      blocks.push(bytes.subarray(p, p + len));
      p += len;
    }
  };

  const frames = [];
  let loop = null;
  let control = null; // the graphic control extension for the next image
  for (;;) {
    need(1);
    const type = bytes[p++];
    if (type === 0x3b) break; // trailer
    if (type === 0x21) {
      need(1);
      const label = bytes[p++];
      const blocks = subBlocks();
      if (label === 0xf9 && blocks[0] && blocks[0].length >= 4) {
        const b = blocks[0];
        const cs = b[1] | (b[2] << 8);
        control = {
          disposal: (b[0] >> 2) & 7,
          transparent: b[0] & 1 ? b[3] : null,
          delay: cs * 10 < 20 ? 100 : cs * 10,
        };
      } else if (label === 0xff && blocks.length >= 2 && isLoopApp(blocks[0])) {
        const b = blocks[1];
        if (b.length >= 3 && b[0] === 1) loop = b[1] | (b[2] << 8);
      }
      continue;
    }
    if (type !== 0x2c) throw new Error('not a GIF: unknown block');
    need(9);
    const x = u16(p);
    const y = u16(p + 2);
    const w = u16(p + 4);
    const h = u16(p + 6);
    const flags = bytes[p + 8];
    p += 9;
    let palette = globalPalette;
    if (flags & 0x80) {
      const n = 3 * (1 << ((flags & 7) + 1));
      need(n);
      palette = bytes.subarray(p, p + n);
      p += n;
    }
    if (!palette) throw new Error('not a GIF: no colour table');
    need(1);
    const minCodeSize = bytes[p++];
    const data = subBlocks();
    const c = control || { disposal: 0, transparent: null, delay: 100 };
    frames.push({
      x, y, w, h,
      delay: c.delay,
      // 4-7 are undefined; browsers treat them as "leave it"
      disposal: c.disposal > 3 ? 1 : c.disposal,
      transparent: c.transparent,
      interlaced: (flags & 0x40) !== 0,
      palette, minCodeSize, data,
    });
    control = null;
  }
  if (!frames.length) throw new Error('not a GIF: no frames');
  return { width, height, loop, frames };
}

function isGifHeader(b) {
  // "GIF87a" or "GIF89a"
  return b[0] === 0x47 && b[1] === 0x49 && b[2] === 0x46 && b[3] === 0x38
    && (b[4] === 0x37 || b[4] === 0x39) && b[5] === 0x61;
}

function isLoopApp(b) {
  const id = String.fromCharCode(...b);
  return id === 'NETSCAPE2.0' || id === 'ANIMEXTS1.0';
}

const MAX_CODES = 4096;

/** LZW-decode one frame: one palette index per pixel, w*h of them, in row
 * order (an interlaced frame is put back). Pixels the data stops short of
 * stay 0. */
export function decodeIndices(frame) {
  const { w, h, minCodeSize, data } = frame;
  const n = w * h;
  const out = new Uint8Array(n);
  let total = 0;
  for (const b of data) total += b.length;
  const bytes = new Uint8Array(total);
  let at = 0;
  for (const b of data) { bytes.set(b, at); at += b.length; }

  const clear = 1 << minCodeSize;
  const eoi = clear + 1;
  const prefix = new Uint16Array(MAX_CODES);
  const suffix = new Uint8Array(MAX_CODES);
  const stack = new Uint8Array(MAX_CODES + 1);
  for (let i = 0; i < clear; i++) suffix[i] = i;

  let size = minCodeSize + 1;
  let mask = (1 << size) - 1;
  let avail = clear + 2;
  let old = -1;
  let first = 0;
  let acc = 0;
  let bits = 0;
  let pos = 0;
  let op = 0;
  while (op < n) {
    while (bits < size && pos < total) { acc |= bytes[pos++] << bits; bits += 8; }
    if (bits < size) break; // data ran out
    let code = acc & mask;
    acc >>>= size;
    bits -= size;
    if (code === clear) {
      size = minCodeSize + 1;
      mask = (1 << size) - 1;
      avail = clear + 2;
      old = -1;
      continue;
    }
    if (code === eoi) break;
    if (old === -1) {
      if (code >= clear) break; // a first code must be a root
      out[op++] = suffix[code];
      old = first = code;
      continue;
    }
    const incoming = code;
    let sp = 0;
    if (code >= avail) {
      if (code > avail) break; // corrupt
      stack[sp++] = first; // KwKwK: the code being defined right now
      code = old;
    }
    while (code > eoi) { stack[sp++] = suffix[code]; code = prefix[code]; }
    first = suffix[code];
    stack[sp++] = first;
    if (avail < MAX_CODES) {
      prefix[avail] = old;
      suffix[avail] = first;
      avail++;
      if ((avail & mask) === 0 && avail < MAX_CODES) { size++; mask = (1 << size) - 1; }
    }
    old = incoming;
    while (sp > 0 && op < n) out[op++] = stack[--sp];
  }
  return frame.interlaced ? deinterlace(out, w, h) : out;
}

function deinterlace(src, w, h) {
  const out = new Uint8Array(src.length);
  let row = 0;
  for (const [start, step] of [[0, 8], [4, 8], [2, 4], [1, 2]]) {
    for (let r = start; r < h; r += step, row++) {
      out.set(src.subarray(row * w, row * w + w), r * w);
    }
  }
  return out;
}

/**
 * The composited picture of any frame, on demand.
 *
 * Reaching frame i means drawing frames 0..i in turn, so the compositor keeps
 * a full copy of the picture every `interval` frames as it goes and starts
 * from the nearest one at or before i. The interval is chosen so the copies
 * fit in `budget` bytes, give or take one frame. They are a cache:
 * `dropCache()` frees them and the next pass forward rebuilds them.
 *
 * Measured on robotics' largest GIF (door-frames, 960x640, 80 frames) at the
 * default budget: a copy every 12 frames (16.4 MiB), 2-4 ms per frame forward,
 * at most ~24 ms for a step back, ~150 ms for a step back after dropCache().
 */
export class Compositor {
  constructor(gif, { budget = 16 * 2 ** 20 } = {}) {
    this.gif = gif;
    const n = gif.frames.length;
    const frameBytes = gif.width * gif.height * 4;
    this.interval = Math.min(n, Math.max(1, Math.ceil((n * frameBytes) / budget)));
    this.pixels = new Uint8ClampedArray(frameBytes);
    this.current = -1;     // the frame this.pixels shows; -1 = nothing drawn
    this.restore = null;   // what a disposal-3 frame drew over, for undoing it
    this.snapshots = new Map();
  }

  /** RGBA of frame i, width*height*4 bytes. The array is the compositor's
   * own and changes on the next call. */
  frame(i) {
    const n = this.gif.frames.length;
    if (!Number.isInteger(i) || i < 0 || i >= n) throw new RangeError(`no frame ${i}`);
    if (i === this.current) return this.pixels;
    // the nearest snapshot at or before i
    let s = i - (i % this.interval);
    while (s >= 0 && !this.snapshots.has(s)) s -= this.interval;
    if (!(this.current < i && this.current >= s)) {
      if (s >= 0) {
        const snap = this.snapshots.get(s);
        this.pixels.set(snap.pixels);
        this.restore = snap.restore && { ...snap.restore, pixels: snap.restore.pixels.slice() };
        this.current = s;
      } else {
        this.pixels.fill(0);
        this.restore = null;
        this.current = -1;
      }
    }
    while (this.current < i) {
      this.step();
      const j = this.current;
      if (j % this.interval === 0 && !this.snapshots.has(j)) {
        this.snapshots.set(j, {
          pixels: this.pixels.slice(),
          restore: this.restore && { ...this.restore, pixels: this.restore.pixels.slice() },
        });
      }
    }
    return this.pixels;
  }

  dropCache() {
    this.snapshots.clear();
  }

  /** Draw the next frame over the current picture. */
  step() {
    const { frames, width, height } = this.gif;
    const prev = this.current >= 0 ? frames[this.current] : null;
    if (prev && prev.disposal === 2) this.clear(prev);
    if (prev && prev.disposal === 3 && this.restore) this.put(this.restore);
    this.restore = null;

    const f = frames[this.current + 1];
    const x0 = Math.min(f.x, width);
    const y0 = Math.min(f.y, height);
    const x1 = Math.min(f.x + f.w, width);
    const y1 = Math.min(f.y + f.h, height);
    if (f.disposal === 3) this.restore = this.take(x0, y0, x1, y1);

    const idx = decodeIndices(f);
    const pal = f.palette;
    const px = this.pixels;
    const t = f.transparent;
    for (let y = y0; y < y1; y++) {
      let src = (y - f.y) * f.w + (x0 - f.x);
      let dst = (y * width + x0) * 4;
      for (let x = x0; x < x1; x++, src++, dst += 4) {
        const c = idx[src];
        if (c === t) continue;
        const k = c * 3;
        px[dst] = pal[k];
        px[dst + 1] = pal[k + 1];
        px[dst + 2] = pal[k + 2];
        px[dst + 3] = 255;
      }
    }
    this.current++;
  }

  clear(f) {
    const { width, height } = this.gif;
    const x1 = Math.min(f.x + f.w, width);
    const y1 = Math.min(f.y + f.h, height);
    for (let y = Math.min(f.y, height); y < y1; y++) {
      this.pixels.fill(0, (y * width + Math.min(f.x, width)) * 4, (y * width + x1) * 4);
    }
  }

  take(x0, y0, x1, y1) {
    const { width } = this.gif;
    const rw = x1 - x0;
    const pixels = new Uint8ClampedArray(Math.max(0, rw * (y1 - y0) * 4));
    for (let y = y0; y < y1; y++) {
      pixels.set(this.pixels.subarray((y * width + x0) * 4, (y * width + x1) * 4),
        (y - y0) * rw * 4);
    }
    return { x0, y0, x1, y1, pixels };
  }

  put({ x0, y0, x1, y1, pixels }) {
    const { width } = this.gif;
    const rw = x1 - x0;
    for (let y = y0; y < y1; y++) {
      this.pixels.set(pixels.subarray((y - y0) * rw * 4, (y - y0 + 1) * rw * 4),
        (y * width + x0) * 4);
    }
  }
}

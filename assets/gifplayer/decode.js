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

/**
 * Compressing a save on its way out.
 *
 * A save carries the reader's whole section, so it is both large and highly
 * repetitive — thousands of short numbers and the same path syntax over and
 * over. A dense section measured 1.73 MB of JSON and 0.60 MB gzipped, so this
 * is the cheapest remaining win on upload cost: no protocol change, no stored
 * format change, just fewer bytes leaving the tablet (task #667).
 *
 * Brotli would do better still — 4.7x against gzip's 2.9x on the same body —
 * but `CompressionStream` does not offer it in Safari, and Safari is what is
 * on the iPads.
 *
 * Everything here fails open. A missing API, a throwing stream, a proxy that
 * mangles the body: every one of those ends with the save going out
 * uncompressed rather than not going out at all.
 */

/**
 * Below this, send plain bytes.
 *
 * Gzip framing plus the round trip through a stream costs more than it saves
 * on a small body, and most saves are small — the reader draws one stroke and
 * the debounce fires.
 */
export const COMPRESS_ABOVE_BYTES = 64 * 1024;

/**
 * Whether compression has been switched off for the rest of this session.
 *
 * A gzipped *request* body is unusual, and this one crosses Cloudflare and
 * nginx before Django reads it. If any of that chain mangles it the reader
 * must fall back to what worked yesterday, not retry a broken request until
 * they give up. One rejection is enough to stop trying.
 */
export class Downgrade {
  constructor() {
    this.off = false;
  }

  /** Read a failed save's status. Only encoding complaints disable us. */
  note(status) {
    // 400: the body was not valid gzip by the time it arrived.
    // 415: something in the chain does not speak it at all.
    // Anything else — 413 too much ink, 5xx server trouble — says nothing
    // about the encoding, and switching off would only make the retry bigger.
    if (status === 400 || status === 415) this.off = true;
  }
}

async function gzip(text, Stream) {
  const stream = new Stream('gzip');
  const writer = stream.writable.getWriter();
  writer.write(new TextEncoder().encode(text));
  writer.close();
  const chunks = [];
  const reader = stream.readable.getReader();
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
  }
  let total = 0;
  for (const c of chunks) total += c.length;
  const out = new Uint8Array(total);
  let at = 0;
  for (const c of chunks) { out.set(c, at); at += c.length; }
  return out;
}

/**
 * `{ body, encoding }` for a request — compressed when that is worth doing and
 * known to work, and the original string otherwise.
 */
export async function maybeGzip(text, options = {}) {
  const { downgrade } = options;
  // Read the key rather than defaulting the parameter: an explicit
  // `Stream: undefined` means "this browser has none", and a default would
  // quietly substitute the real one.
  const Stream = 'Stream' in options ? options.Stream : globalThis.CompressionStream;
  const plain = { body: text, encoding: null };
  if (!Stream) return plain;
  if (downgrade && downgrade.off) return plain;
  if (text.length < COMPRESS_ABOVE_BYTES) return plain;
  try {
    return { body: await gzip(text, Stream), encoding: 'gzip' };
  } catch (err) {
    return plain;                 // never let this be why a save fails
  }
}

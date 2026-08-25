import test from 'node:test';
import assert from 'node:assert/strict';
import { gunzipSync } from 'node:zlib';
import { COMPRESS_ABOVE_BYTES, maybeGzip, Downgrade } from './compress.js';

const big = (n) => JSON.stringify({ d: 'M 1 2 ' + 'L 3 4 '.repeat(n) });

test('a small body is sent as it is', async () => {
  // Below the threshold the framing costs more than it saves, and a quick
  // save should stay quick.
  const body = '{"strokes":{}}';
  const out = await maybeGzip(body, { downgrade: new Downgrade() });
  assert.equal(out.body, body);
  assert.equal(out.encoding, null);
});

test('a large body is gzipped', async () => {
  const body = big(20000);
  assert.ok(body.length > COMPRESS_ABOVE_BYTES);
  const out = await maybeGzip(body, { downgrade: new Downgrade() });
  assert.equal(out.encoding, 'gzip');
  assert.ok(out.body.byteLength < body.length / 2);
});

test('what it sends decompresses back to what it was given', async () => {
  const body = big(20000);
  const out = await maybeGzip(body, { downgrade: new Downgrade() });
  assert.equal(gunzipSync(Buffer.from(out.body)).toString(), body);
});

test('without CompressionStream it sends plain bytes', async () => {
  // Not every browser the students use has it, and a missing API must not
  // stop a save.
  const out = await maybeGzip(big(20000), { downgrade: new Downgrade(), Stream: undefined });
  assert.equal(out.encoding, null);
  assert.equal(typeof out.body, 'string');
});

test('a compression that throws falls back rather than failing the save', async () => {
  const Boom = class { constructor() { throw new Error('nope'); } };
  const out = await maybeGzip(big(20000), { downgrade: new Downgrade(), Stream: Boom });
  assert.equal(out.encoding, null);
  assert.equal(typeof out.body, 'string');
});

test('once the server rejects a compressed body, it stops compressing', async () => {
  // A gzipped REQUEST is unusual and passes through Cloudflare and nginx
  // before Django sees it. If anything in that chain mangles it, the reader
  // must degrade to today's behaviour, not lose their saves (task #667).
  const downgrade = new Downgrade();
  assert.equal((await maybeGzip(big(20000), { downgrade })).encoding, 'gzip');
  downgrade.note(400);
  const out = await maybeGzip(big(20000), { downgrade });
  assert.equal(out.encoding, null);
});

test('415 also downgrades', async () => {
  const downgrade = new Downgrade();
  downgrade.note(415);
  assert.equal(downgrade.off, true);
});

test('an ordinary failure does not disable compression', async () => {
  // 413 means too much ink, 500 means the server fell over. Neither says
  // anything about the encoding, and turning compression off would make the
  // next attempt bigger.
  const downgrade = new Downgrade();
  downgrade.note(413);
  downgrade.note(500);
  assert.equal(downgrade.off, false);
});

test('the threshold is where framing stops mattering', () => {
  assert.ok(COMPRESS_ABOVE_BYTES >= 16 * 1024);
  assert.ok(COMPRESS_ABOVE_BYTES <= 128 * 1024);
});

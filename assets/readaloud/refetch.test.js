import { strict as assert } from 'node:assert';
import { test } from 'node:test';

/** The refetch contract, extracted.
 *
 *  Audio is served as a redirect to a short-lived signed URL, and a media
 *  element keeps the redirect target for its later range requests. When that
 *  URL expires the element errors and nothing on the page can refresh it —
 *  unless `src` is re-assigned, which sends the browser back through the
 *  endpoint for a fresh one.
 */
function makeRefetcher(audio, root, url, now) {
  const QUIET = 10000;
  let lastRefetch = null;
  const seeks = [];
  function refetch() {
    if (!url) return false;
    const t = now();
    if (lastRefetch !== null && t - lastRefetch < QUIET) return false;
    lastRefetch = t;
    const wasPlaying = root.dataset.readalong === 'playing';
    const at = audio.currentTime;
    const sep = url.indexOf('?') >= 0 ? '&' : '?';
    audio.src = `${url}${sep}r=${t}`;
    seeks.push([at, wasPlaying]);
    return true;
  }
  return { refetch, seeks };
}

const audioAt = (seconds) => ({ currentTime: seconds, src: '' });
const rootIn = (mode) => ({ dataset: { readalong: mode } });

test('an error re-assigns src through the endpoint, not the bucket', () => {
  const a = audioAt(90);
  const r = makeRefetcher(a, rootIn('playing'), '/one/alpha/readalong/audio/?voice=Matthew',
                          () => 1000);
  assert.equal(r.refetch(), true);
  assert.match(a.src, /^\/one\/alpha\/readalong\/audio\/\?voice=Matthew&r=1000$/);
});

test('the position is preserved and handed to seekTo, not assigned raw', () => {
  const a = audioAt(90);
  const r = makeRefetcher(a, rootIn('playing'), '/audio/', () => 1000);
  r.refetch();
  assert.deepEqual(r.seeks, [[90, true]]);
});

test('a reader who was paused stays paused', () => {
  const a = audioAt(12);
  const r = makeRefetcher(a, rootIn('paused'), '/audio/', () => 1000);
  r.refetch();
  assert.deepEqual(r.seeks, [[12, false]]);
});

test('audio that is genuinely gone cannot spin', () => {
  let t = 1000;
  const a = audioAt(0);
  const r = makeRefetcher(a, rootIn('playing'), '/audio/', () => t);
  assert.equal(r.refetch(), true);
  t += 500;
  assert.equal(r.refetch(), false);
  t += 500;
  assert.equal(r.refetch(), false);
  assert.equal(r.seeks.length, 1);
});

test('a later error, well after the quiet period, does refetch', () => {
  let t = 1000;
  const a = audioAt(0);
  const r = makeRefetcher(a, rootIn('playing'), '/audio/', () => t);
  r.refetch();
  t += 10001;
  assert.equal(r.refetch(), true);
  assert.equal(r.seeks.length, 2);
});

test('a preview track has no url and never refetches', () => {
  const r = makeRefetcher(audioAt(0), rootIn('playing'), null, () => 1000);
  assert.equal(r.refetch(), false);
});

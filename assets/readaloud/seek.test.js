import { strict as assert } from 'node:assert';
import { test } from 'node:test';

/** The seekTo contract, extracted: a seek before metadata must be applied
 *  when metadata arrives, not silently dropped. */
function makeSeeker(audio) {
  let pendingSeek = null;
  const played = [];
  const play = () => played.push(audio.currentTime);
  function seekTo(seconds, thenPlay) {
    const at = Math.max(0, seconds || 0);
    const apply = () => {
      audio.currentTime = at;
      pendingSeek = null;
      if (thenPlay) play();
    };
    if (audio.readyState >= 1) { apply(); return; }
    pendingSeek = at;
    audio.addEventListener('loadedmetadata', () => {
      if (pendingSeek === at) apply();
    }, { once: true });
  }
  return { seekTo, played, pending: () => pendingSeek };
}

function fakeAudio(readyState) {
  const l = {};
  return {
    readyState, currentTime: 0,
    addEventListener(t, fn) { (l[t] = l[t] || []).push(fn); },
    fire(t) { (l[t] || []).forEach((fn) => fn()); l[t] = []; },
  };
}

test('a seek with metadata applies at once', () => {
  const a = fakeAudio(4);
  const s = makeSeeker(a);
  s.seekTo(12, true);
  assert.equal(a.currentTime, 12);
  assert.deepEqual(s.played, [12]);
});

test('a seek BEFORE metadata is applied when it arrives, not dropped', () => {
  // This is the bug: the browser silently discards the assignment and starts
  // playback at zero.
  const a = fakeAudio(0);
  const s = makeSeeker(a);
  s.seekTo(12, true);
  assert.equal(a.currentTime, 0, 'cannot seek yet');
  assert.deepEqual(s.played, [], 'and must not start at zero meanwhile');
  a.fire('loadedmetadata');
  assert.equal(a.currentTime, 12);
  assert.deepEqual(s.played, [12]);
});

test('a later seek supersedes an earlier pending one', () => {
  const a = fakeAudio(0);
  const s = makeSeeker(a);
  s.seekTo(12);
  s.seekTo(30);
  a.fire('loadedmetadata');
  assert.equal(a.currentTime, 30);
});

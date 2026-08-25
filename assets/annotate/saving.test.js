import test from 'node:test';
import assert from 'node:assert/strict';
import { Saver, OK, SAVING, FAILED } from './saving.js';

/** A stand-in for InkApi whose answers the test chooses. */
function fakeApi(answers) {
  const sent = [];
  let i = 0;
  return {
    sent,
    async save(body) {
      sent.push(body);
      const answer = answers[Math.min(i, answers.length - 1)];
      i += 1;
      return answer;
    },
  };
}

/** setTimeout the test drives by hand. */
function fakeClock() {
  let pending = null;
  return {
    setTimer: (fn) => { pending = fn; return 1; },
    clearTimer: () => { pending = null; },
    get scheduled() { return pending !== null; },
    async tick() { const fn = pending; pending = null; if (fn) await fn(); },
  };
}

function saver(answers, extra = {}) {
  const api = fakeApi(answers);
  const clock = fakeClock();
  const states = [];
  const s = new Saver(api, {
    onState: (state) => states.push(state),
    setTimer: clock.setTimer,
    clearTimer: clock.clearTimer,
    ...extra,
  });
  return { s, api, clock, states };
}

test('a save that lands reports ok', async () => {
  const { s, states } = saver([true]);
  await s.save(() => ({ strokes: {} }));
  assert.deepEqual(states, [SAVING, OK]);
});

test('a save that fails says so instead of failing quietly', async () => {
  // The whole point: a reader whose ink is not reaching the server has to be
  // told, or they keep annotating into a void (task #667).
  const { s, states } = saver([false]);
  await s.save(() => ({ strokes: {} }));
  assert.equal(states.at(-1), FAILED);
});

test('a failed save schedules its own retry', async () => {
  const { s, clock } = saver([false]);
  await s.save(() => ({ strokes: {} }));
  assert.ok(clock.scheduled);
});

test('the retry sends the ink as it is now, not as it was when it failed', async () => {
  // The reader keeps drawing while the save is broken. Re-reading the payload
  // is what makes the eventual success carry everything.
  let strokes = { 1: ['a'] };
  const { s, api, clock } = saver([false, true]);
  await s.save(() => ({ strokes }));
  strokes = { 1: ['a', 'b'] };
  await clock.tick();
  assert.deepEqual(api.sent.at(-1).strokes, { 1: ['a', 'b'] });
});

test('a retry that lands clears the warning', async () => {
  const { s, clock, states } = saver([false, true]);
  await s.save(() => ({ strokes: {} }));
  await clock.tick();
  assert.equal(states.at(-1), OK);
});

test('a retry that fails again keeps trying', async () => {
  const { s, clock } = saver([false]);
  await s.save(() => ({ strokes: {} }));
  await clock.tick();
  assert.ok(clock.scheduled);
});

test('a save requested while one is in flight does not double-post', async () => {
  // A section runs to megabytes; two of them on the wire at once would race
  // to be the last writer as well as wasting the reader's uplink.
  const releases = [];
  const api = { sent: [], save(body) { api.sent.push(body); return new Promise((r) => releases.push(r)); } };
  const s = new Saver(api, { setTimer: () => 1, clearTimer: () => {} });
  const first = s.save(() => ({ n: 1 }));
  const second = s.save(() => ({ n: 2 }));
  assert.equal(api.sent.length, 1);   // the second is held, not sent alongside
  releases[0](true);
  await Promise.resolve();            // let the follow-up round go out
  await new Promise((r) => setImmediate(r));
  releases[1](true);
  await first; await second;
  // The one that was asked for mid-flight still happens, with fresh state.
  assert.equal(api.sent.length, 2);
  assert.deepEqual(api.sent.at(-1), { n: 2 });
});

test('it knows whether anything is still unsaved', async () => {
  const { s } = saver([false]);
  assert.equal(s.pending, false);
  await s.save(() => ({ strokes: {} }));
  assert.equal(s.pending, true);
});

test('nothing is pending once a save lands', async () => {
  const { s } = saver([true]);
  await s.save(() => ({ strokes: {} }));
  assert.equal(s.pending, false);
});

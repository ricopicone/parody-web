import test from 'node:test';
import assert from 'node:assert/strict';
import { Controller } from './controller.js';

/** A clock the test turns by hand: schedule() queues, tick() runs the next
 * live callback, cancel() kills one. */
function harness({ count = 4, delays = [50, 450, 50, 850], loop = 0 } = {}) {
  const queue = [];
  const rendered = [];
  const changes = [];
  const ctl = new Controller({
    count, delays, loop,
    render: (i) => rendered.push(i),
    schedule: (fn, ms) => { const h = { fn, ms, live: true }; queue.push(h); return h; },
    cancel: (h) => { if (h) h.live = false; },
    onChange: (s) => changes.push({ ...s }),
  });
  const live = () => queue.filter((h) => h.live);
  const tick = () => {
    const h = live()[0];
    assert.ok(h, 'nothing scheduled');
    h.live = false;
    h.fn();
    return h.ms;
  };
  return { ctl, rendered, changes, live, tick };
}

test('play shows the current frame and schedules the next after its delay', () => {
  const { ctl, rendered, live } = harness();
  ctl.play();
  assert.deepEqual(rendered, [0]);
  assert.equal(ctl.state.playing, true);
  assert.deepEqual(live().map((h) => h.ms), [50]);
});

test('each frame waits its own delay', () => {
  const { ctl, rendered, tick } = harness();
  ctl.play();
  assert.equal(tick(), 50);  // frame 0 held 50 ms
  assert.equal(tick(), 450); // frame 1 held 450 ms
  assert.equal(tick(), 50);
  assert.deepEqual(rendered, [0, 1, 2, 3]);
});

test('a looping GIF wraps from the last frame to the first', () => {
  const { ctl, rendered, tick } = harness({ loop: 0 });
  ctl.play();
  for (let i = 0; i < 4; i++) tick();
  assert.deepEqual(rendered, [0, 1, 2, 3, 0]);
  assert.equal(ctl.state.playing, true);
});

test('a GIF that plays once stops on its last frame', () => {
  const { ctl, rendered, live, tick } = harness({ loop: null });
  ctl.play();
  for (let i = 0; i < 3; i++) tick();
  assert.deepEqual(rendered, [0, 1, 2, 3]);
  assert.equal(ctl.state.playing, false);
  assert.equal(live().length, 0);
});

test('play from the last frame of a play-once GIF starts again at the first', () => {
  const { ctl, rendered } = harness({ loop: null });
  ctl.last();
  ctl.play();
  assert.deepEqual(rendered, [3, 0]);
  assert.equal(ctl.state.playing, true);
});

test('stepping pauses and moves one frame, wrapping at both ends', () => {
  const { ctl, rendered, live } = harness();
  ctl.play();
  ctl.step(-1);
  assert.equal(ctl.state.playing, false);
  assert.equal(live().length, 0);
  assert.equal(ctl.state.frame, 3);
  ctl.step(+1);
  assert.equal(ctl.state.frame, 0);
  ctl.step(+1);
  assert.deepEqual(rendered, [0, 3, 0, 1]);
});

test('seek, first and last pause and stay inside the animation', () => {
  const { ctl, live } = harness();
  ctl.play();
  ctl.seek(2);
  assert.deepEqual([ctl.state.frame, ctl.state.playing, live().length], [2, false, 0]);
  ctl.seek(99);
  assert.equal(ctl.state.frame, 3);
  ctl.seek(-5);
  assert.equal(ctl.state.frame, 0);
  ctl.seek('2'); // a range input's value is a string
  assert.equal(ctl.state.frame, 2);
  ctl.last();
  assert.equal(ctl.state.frame, 3);
  ctl.first();
  assert.equal(ctl.state.frame, 0);
});

test('toggle flips between playing and paused', () => {
  const { ctl, live } = harness();
  ctl.toggle();
  assert.equal(ctl.state.playing, true);
  ctl.toggle();
  assert.equal(ctl.state.playing, false);
  assert.equal(live().length, 0);
});

test('pausing keeps the frame where it is', () => {
  const { ctl, tick } = harness();
  ctl.play();
  tick();
  ctl.pause();
  assert.equal(ctl.state.frame, 1);
});

test('every frame change renders, then reports the new state', () => {
  const { ctl, changes } = harness();
  ctl.seek(2);
  assert.deepEqual(changes.at(-1), { frame: 2, playing: false });
  ctl.play();
  assert.deepEqual(changes.at(-1), { frame: 2, playing: true });
  ctl.pause();
  assert.deepEqual(changes.at(-1), { frame: 2, playing: false });
});

test('offscreen pause does not override the reader\'s pause', () => {
  const paused = harness();
  paused.ctl.play();
  paused.ctl.pause();
  paused.ctl.setVisible(false);
  paused.ctl.setVisible(true);
  assert.equal(paused.ctl.state.playing, false);
  assert.equal(paused.live().length, 0);

  const playing = harness();
  playing.ctl.play();
  playing.ctl.setVisible(false);
  assert.equal(playing.live().length, 0, 'no timer while out of view');
  assert.equal(playing.ctl.state.playing, true, 'still meant to be playing');
  playing.ctl.setVisible(true);
  assert.deepEqual(playing.live().map((h) => h.ms), [50]);
});

test('play while out of view waits until the figure is seen', () => {
  const { ctl, live } = harness();
  ctl.setVisible(false);
  ctl.play();
  assert.equal(live().length, 0);
  ctl.setVisible(true);
  assert.equal(live().length, 1);
});

test('becoming visible twice does not double the timer', () => {
  const { ctl, live } = harness();
  ctl.play();
  ctl.setVisible(true);
  ctl.setVisible(true);
  assert.equal(live().length, 1);
});

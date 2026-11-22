import test from 'node:test';
import assert from 'node:assert/strict';
import { Controller } from './controller.js';

/** A clock the test turns by hand: schedule() queues, tick() moves the clock
 * to the next live callback's time (plus `late` ms, as a real timer may be)
 * and runs it, cancel() kills one. Each render costs `cost` ms of clock. */
function harness({ count = 4, delays = [50, 450, 50, 850], loop = 0, cost = 0 } = {}) {
  const queue = [];
  const rendered = [];
  const changes = [];
  const clock = { t: 0 };
  const ctl = new Controller({
    count, delays, loop,
    render: (i) => { rendered.push(i); clock.t += cost; },
    schedule: (fn, ms) => {
      const h = { fn, ms, at: clock.t + ms, live: true };
      queue.push(h);
      return h;
    },
    cancel: (h) => { if (h) h.live = false; },
    now: () => clock.t,
    onChange: (s) => changes.push({ ...s }),
  });
  const live = () => queue.filter((h) => h.live);
  const tick = ({ late = 0 } = {}) => {
    const h = live()[0];
    assert.ok(h, 'nothing scheduled');
    h.live = false;
    clock.t = h.at + late;
    h.fn();
    return h.ms;
  };
  return { ctl, rendered, changes, live, tick, clock };
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

test('drawing time and a late timer come out of the next wait', () => {
  // every frame drawn takes 4 ms; waiting a full delay AFTER drawing ran a
  // 50 ms GIF about 8% slow. Each frame is due a delay after the last was due.
  // (tick() answers the wait it fired, which was set when the frame before
  // was drawn)
  const { ctl, tick } = harness({ cost: 4 });
  ctl.play();                     // frame 0 drawn by 4; frame 1 due at 54
  assert.equal(tick(), 50);       // frame 1 drawn by 58; frame 2 due at 504
  assert.equal(tick(), 450 - 4);  // frame 2 drawn by 508; frame 3 due at 554
  assert.equal(tick({ late: 3 }), 50 - 4); // fired at 557, drawn by 561
  assert.equal(tick(), 850 - 7);  // frame 0 still due at 1404
});

test('a timer far behind waits a full delay, never a burst of frames', () => {
  // a busy page or a background tab: a deadline long past is dropped, not
  // caught up on by showing frames back to back
  const { ctl, tick, live } = harness();
  ctl.play();
  tick({ late: 5000 });
  assert.deepEqual(live().map((h) => h.ms), [450]);
});

test('after a pause the frame gets its whole delay again', () => {
  const { ctl, tick, live, clock } = harness();
  ctl.play();
  tick();
  clock.t += 20;
  ctl.pause();
  clock.t += 3000;
  ctl.play();
  assert.deepEqual(live().map((h) => h.ms), [450]);
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

// The NETSCAPE count is how many times to play AGAIN after the first time:
// Chrome reports loop count 2 as repetitionCount 2, three plays in all.
test('a GIF that loops twice plays three times, then stops on its last frame', () => {
  const { ctl, rendered, live, tick } = harness({ loop: 2 });
  ctl.play();
  for (let i = 0; i < 11; i++) tick();
  assert.deepEqual(rendered, [0, 1, 2, 3, 0, 1, 2, 3, 0, 1, 2, 3]);
  assert.equal(ctl.state.playing, false);
  assert.equal(live().length, 0);
});

test('play after the loops have run out plays them all again', () => {
  const { ctl, rendered, live, tick } = harness({ loop: 1 });
  ctl.play();
  for (let i = 0; i < 7; i++) tick();
  assert.equal(ctl.state.playing, false);
  rendered.length = 0;
  ctl.play();
  for (let i = 0; i < 7; i++) tick();
  assert.deepEqual(rendered, [0, 1, 2, 3, 0, 1, 2, 3]);
  assert.equal(ctl.state.playing, false);
  assert.equal(live().length, 0);
});

test('a pause partway through does not restart the count', () => {
  const { ctl, rendered, tick } = harness({ loop: 1 });
  ctl.play();
  for (let i = 0; i < 5; i++) tick(); // into the second play, at frame 1
  ctl.pause();
  ctl.play();
  tick();
  tick();
  assert.deepEqual(rendered, [0, 1, 2, 3, 0, 1, 1, 2, 3]);
  assert.equal(ctl.state.playing, false);
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

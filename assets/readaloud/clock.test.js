import { strict as assert } from 'node:assert';
import { test } from 'node:test';
import { Clock } from './clock.js';

test('starts paused at zero', () => {
  const c = new Clock(1000);
  assert.equal(c.paused, true);
  assert.equal(c.currentTime, 0);
});

test('play then pause accumulates elapsed time', async () => {
  const c = new Clock(10000);
  c.play();
  assert.equal(c.paused, false);
  await new Promise((r) => setTimeout(r, 25));
  c.pause();
  const held = c.currentTime;
  assert.ok(held > 0, 'time must advance while playing');
  await new Promise((r) => setTimeout(r, 25));
  assert.equal(c.currentTime, held, 'must not advance while paused');
});

test('seeking sets the position', () => {
  const c = new Clock(10000);
  c.currentTime = 2.5;
  assert.equal(c.currentTime, 2.5);
});

test('ended listeners fire when dispatched', () => {
  const c = new Clock(10);
  let fired = 0;
  c.addEventListener('ended', () => { fired += 1; });
  c.dispatch('ended');
  assert.equal(fired, 1);
});

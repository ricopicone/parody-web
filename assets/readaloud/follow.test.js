import { strict as assert } from 'node:assert';
import { test } from 'node:test';
import { Follower } from './follow.js';

const VIEW = 600;          // scroller height; reach is a third of it

test('asks once for a destination, not once per frame', () => {
  const f = new Follower();
  // The mark is far below the viewport, and the frame loop asks 60 times
  // while the smooth scroll is still crawling towards it.
  let asked = 0;
  let scrollTop = 0;
  for (let i = 0; i < 60; i += 1) {
    const to = f.target(2000, scrollTop, VIEW);
    if (to !== null) asked += 1;
    scrollTop += 5;                    // the smooth scroll, inching along
  }
  assert.equal(asked, 1, 'one journey, one request');
});

test('a genuinely new destination is followed', () => {
  const f = new Follower();
  assert.equal(f.target(2000, 0, VIEW), 2000);
  assert.equal(f.target(2010, 10, VIEW), null, 'the same journey');
  assert.equal(f.target(5000, 20, VIEW), 5000, 'a new page, a new request');
});

test('nothing is asked while the line is already on screen', () => {
  const f = new Follower();
  assert.equal(f.target(100, 0, VIEW), null);
});

test('arriving clears the memory, so the next departure is honoured', () => {
  const f = new Follower();
  assert.equal(f.target(2000, 0, VIEW), 2000);
  assert.equal(f.target(2000, 2000, VIEW), null, 'arrived');
  assert.equal(f.target(2000, 0, VIEW), 2000,
               'scrolled away by hand: ask again');
});

test('a manual scroll resets it', () => {
  const f = new Follower();
  f.target(2000, 0, VIEW);
  f.reset();
  assert.equal(f.target(2000, 0, VIEW), 2000);
});

/**
 * Handing control back.
 *
 * A manual scroll used to stop the page following the voice for the REST of
 * that playback — `following` was set false by any wheel or touchmove and set
 * true again only by pressing play. And the mark is only drawn on a page the
 * viewer has rasterised, which is a window around the VIEWPORT, not around
 * the voice: so once the two separated, the highlight stopped appearing and
 * nothing brought it back. That is the "gets choppy after I scroll and then
 * never recovers" report.
 */
const clockFrom = (start = 0) => {
  const c = { t: start, now: () => c.t, tick(ms) { c.t += ms; return c; } };
  return c;
};

test('a reader scrolling by hand takes the wheel', () => {
  const c = clockFrom();
  const f = new Follower({ now: c.now, resumeAfterMs: 5000 });
  f.takeOver();
  assert.equal(f.target(2000, 0, VIEW), null, 'the voice does not steer');
});

test('and the voice takes it back once they have stopped', () => {
  const c = clockFrom();
  const f = new Follower({ now: c.now, resumeAfterMs: 5000 });
  f.takeOver();

  c.tick(4999);
  assert.equal(f.target(2000, 0, VIEW), null, 'still theirs');
  c.tick(2);
  assert.equal(f.target(2000, 0, VIEW), 2000, 'settled: follow again');
});

test('scrolling again while it is theirs extends the hold', () => {
  const c = clockFrom();
  const f = new Follower({ now: c.now, resumeAfterMs: 5000 });
  f.takeOver();
  c.tick(4000);
  f.takeOver();                      // still scrolling
  c.tick(4000);                      // 8s since the first, 4s since the last
  assert.equal(f.target(2000, 0, VIEW), null, 'they have not finished');
  c.tick(1001);
  assert.equal(f.target(2000, 0, VIEW), 2000);
});

test('pressing play takes it back at once, without waiting', () => {
  const c = clockFrom();
  const f = new Follower({ now: c.now, resumeAfterMs: 5000 });
  f.takeOver();
  f.resume();
  assert.equal(f.target(2000, 0, VIEW), 2000);
});

test('a hold that has expired is forgotten, not re-checked forever', () => {
  const c = clockFrom();
  const f = new Follower({ now: c.now, resumeAfterMs: 5000 });
  f.takeOver();
  c.tick(6000);
  assert.equal(f.steering(), true);
  assert.equal(f.tookOverAt, null, 'the hold is cleared once it lapses');
});

test('with nobody having scrolled, it steers from the start', () => {
  const f = new Follower({ now: clockFrom().now });
  assert.equal(f.steering(), true);
});

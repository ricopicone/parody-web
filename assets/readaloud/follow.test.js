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

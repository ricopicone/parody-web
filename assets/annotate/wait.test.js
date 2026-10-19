import test from 'node:test';
import assert from 'node:assert/strict';
import { within } from './wait.js';

test('a promise that settles in time gives its value', async () => {
  assert.equal(await within(Promise.resolve('twin'), 50), 'twin');
});

test('a promise that does not settle in time gives null and is let go', async () => {
  let gaveUp = false;
  const never = new Promise(() => {});
  assert.equal(await within(never, 10, () => { gaveUp = true; }), null);
  assert.equal(gaveUp, true);
});

test('letting go is not called when the promise wins', async () => {
  let gaveUp = false;
  await within(Promise.resolve(1), 10, () => { gaveUp = true; });
  await new Promise((r) => setTimeout(r, 20));
  assert.equal(gaveUp, false);
});

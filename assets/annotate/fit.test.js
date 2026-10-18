import test from 'node:test';
import assert from 'node:assert/strict';
import { fitZoom } from './fit.js';

const STEPS = [0.6, 0.75, 0.9, 1, 1.15, 1.35];

test('the largest rung at which the row fits, never above 1', () => {
  // two 540px pages and a 16px gap need 1096px at zoom 1
  assert.equal(fitZoom(1096, 1440, STEPS), 1);
  assert.equal(fitZoom(1096, 1024, STEPS), 0.9);
  assert.equal(fitZoom(1096, 900, STEPS), 0.75);
});

test('when nothing fits, the smallest rung', () => {
  assert.equal(fitZoom(1096, 300, STEPS), 0.6);
});

test('a width it cannot measure leaves the zoom alone', () => {
  assert.equal(fitZoom(0, 1440, STEPS), 1);
  assert.equal(fitZoom(1096, 0, STEPS), 1);
});

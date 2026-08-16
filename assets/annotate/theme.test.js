import test from 'node:test';
import assert from 'node:assert/strict';
import { luminance, isNearBlack, isNearWhite, displayColor } from './theme.js';

const DARK = { dark: true, ink: '#e9e6e0', paper: '#16171a' };
const LIGHT = { dark: false, ink: '#16171a', paper: '#fbfaf7' };

test('luminance spans black to white', () => {
  assert.equal(luminance('#000000'), 0);
  assert.equal(luminance('#ffffff'), 1);
  assert.ok(luminance('#808080') > 0.2 && luminance('#808080') < 0.6);
});

test('shorthand hex is understood', () => {
  assert.equal(luminance('#000'), 0);
  assert.equal(luminance('#fff'), 1);
});

test('the toolbar palette is neither near-black nor near-white', () => {
  // If a chosen colour drifted into either bucket it would start flipping
  // with the theme, which is precisely what must not happen.
  for (const c of ['#2563eb', '#dc2626', '#16a34a', '#f59e0b', '#8b5cf6']) {
    assert.equal(isNearBlack(c), false, `${c} must not read as black`);
    assert.equal(isNearWhite(c), false, `${c} must not read as white`);
  }
  assert.equal(isNearBlack('#000000'), true);
});

test('black ink becomes light on dark paper', () => {
  assert.equal(displayColor('#000000', DARK), '#e9e6e0');
});

test('white ink becomes dark on dark paper', () => {
  assert.equal(displayColor('#ffffff', DARK), '#16171a');
});

test('a colour the reader chose is never changed', () => {
  for (const c of ['#2563eb', '#dc2626', '#16a34a', '#f59e0b', '#8b5cf6']) {
    assert.equal(displayColor(c, DARK), c);
    assert.equal(displayColor(c, LIGHT), c);
  }
});

test('light mode changes nothing at all', () => {
  for (const c of ['#000000', '#ffffff', '#2563eb']) {
    assert.equal(displayColor(c, LIGHT), c);
  }
});

test('an unparseable colour is left alone rather than guessed at', () => {
  // It must not read as luminance 0 and get flipped as if it were black.
  assert.equal(luminance('rebeccapurple'), null);
  assert.equal(isNearBlack('rebeccapurple'), false);
  assert.equal(displayColor('rebeccapurple', DARK), 'rebeccapurple');
  assert.equal(displayColor(undefined, DARK), undefined);
});

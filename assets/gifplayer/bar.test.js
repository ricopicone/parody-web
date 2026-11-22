import test from 'node:test';
import assert from 'node:assert/strict';
import { barView, intersecting, keyAction, placeWidth } from './bar.js';

const ICONS = { play: '<svg>play</svg>', pause: '<svg>pause</svg>' };

/** Stand-ins for the bar's elements that count what is written to them. */
function bar() {
  const writes = { playIcon: 0 };
  let icon = '';
  const play = {
    get innerHTML() { return icon; },
    set innerHTML(v) { icon = v; writes.playIcon++; },
    attrs: {},
    setAttribute(k, v) { this.attrs[k] = v; },
  };
  const scrub = { value: '', attrs: {}, setAttribute(k, v) { this.attrs[k] = v; } };
  const count = { textContent: '', style: {} };
  return { els: { play, scrub, count }, writes };
}

test('the play button\'s icon is replaced only when play/pause changes', () => {
  // Replacing the <svg> under a pressed mouse button cancels the click
  // (Chromium drops a click whose mousedown node left the tree), and frames
  // change every 50 ms, so rewriting it per frame made Pause unclickable.
  const { els, writes } = bar();
  const show = barView(els, 80, ICONS);
  show({ frame: 0, playing: true });
  for (let i = 1; i < 30; i++) show({ frame: i, playing: true });
  assert.equal(writes.playIcon, 1);
  assert.equal(els.play.innerHTML, ICONS.pause);
  show({ frame: 30, playing: false });
  assert.equal(writes.playIcon, 2);
  assert.equal(els.play.innerHTML, ICONS.play);
  assert.equal(els.play.attrs['aria-label'], 'Play (space)');
  assert.equal(els.count.textContent, '31 / 80');
  assert.equal(els.scrub.value, '30');
  assert.equal(els.scrub.attrs['aria-valuetext'], 'Frame 31 of 80');
});

test('the counter is as wide as its longest reading from the start', () => {
  // "100 / 111" is wider than "99 / 111": a counter that grows mid-loop
  // shoves the scrubber sideways every time it passes frame 100
  for (const [n, ch] of [[8, '5ch'], [80, '7ch'], [111, '9ch']]) {
    const { els } = bar();
    barView(els, n, ICONS)({ frame: 0, playing: false });
    assert.equal(els.count.style.minWidth, ch, `${n} frames`);
  }
});

test('PageUp and PageDown step one frame even with the scrubber focused', () => {
  // a focused range input would take them as ±10% (and PageDown as BACK):
  // a lecturer's clicker would jump eight frames the wrong way
  const input = { tagName: 'INPUT' };
  assert.equal(keyAction({ key: 'PageDown', target: input }), 'next');
  assert.equal(keyAction({ key: 'PageUp', target: input }), 'back');
  // arrows, Home and End stay the scrubber's own: they already move it by one
  for (const key of ['ArrowLeft', 'ArrowRight', 'Home', 'End']) {
    assert.equal(keyAction({ key, target: input }), null, key);
  }
});

test('keys on the player itself map to actions; modified keys never do', () => {
  const div = { tagName: 'DIV' };
  assert.equal(keyAction({ key: ' ', target: div }), 'toggle');
  assert.equal(keyAction({ key: 'ArrowRight', target: div }), 'next');
  assert.equal(keyAction({ key: 'f', target: div }), 'full');
  assert.equal(keyAction({ key: 'f', ctrlKey: true, target: div }), null);
  assert.equal(keyAction({ key: 'x', target: div }), null);
  // a focused button answers Space and Enter itself
  assert.equal(keyAction({ key: ' ', target: { tagName: 'BUTTON' } }), null);
});

test('a held Space or F acts once; a held arrow keeps stepping', () => {
  // the auto-repeat of a held key would flicker play/pause, and send the
  // lecture screen in and out of full screen ten times a second
  const div = { tagName: 'DIV' };
  for (const key of [' ', 'k', 'K', 'f', 'F']) {
    assert.equal(keyAction({ key, repeat: true, target: div }), 'held', key);
  }
  assert.equal(keyAction({ key: ' ', repeat: false, target: div }), 'toggle');
  // 'held' is still the player's key, so the page does not scroll under it
  assert.equal(keyAction({ key: 'ArrowRight', repeat: true, target: div }), 'next');
  assert.equal(keyAction({ key: 'PageDown', repeat: true, target: div }), 'next');
  assert.equal(keyAction({ key: 'ArrowLeft', repeat: true, target: div }), 'back');
});

test('a batch of intersection entries is read by its latest entry', () => {
  // scrolled away and straight back between two callbacks: the batch is
  // [left, entered], and reading the first froze a figure that was in view
  assert.equal(intersecting([{ isIntersecting: false }, { isIntersecting: true }]), true);
  assert.equal(intersecting([{ isIntersecting: true }, { isIntersecting: false }]), false);
  assert.equal(intersecting([{ isIntersecting: true }]), true);
});

test('a percentage width is the column\'s: the player takes it, the canvas fills it', () => {
  // on the canvas, 50% would resolve against the player, which shrinks to the
  // canvas: the figure came out a fraction of its own size, not of the column
  assert.deepEqual(placeWidth('50%'), { player: '50%', canvas: '100%' });
  assert.deepEqual(placeWidth('100%'), { player: '100%', canvas: '100%' });
  // any other width is the canvas's own, as it was the image's
  assert.deepEqual(placeWidth('300px'), { player: '', canvas: '300px' });
  assert.deepEqual(placeWidth('3in'), { player: '', canvas: '3in' });
  assert.deepEqual(placeWidth(''), { player: '', canvas: '' });
});

import test from 'node:test';
import assert from 'node:assert/strict';
import { bindHost } from './ink.js';

/** Enough of an element to record what was bound to it. */
function fakeHost(touchAction = '') {
  return {
    style: { touchAction },
    bound: [],
    addEventListener(type, fn) { this.bound.push([type, fn]); },
    removeEventListener(type, fn) {
      const at = this.bound.findIndex(([t, f]) => t === type && f === fn);
      if (at > -1) this.bound.splice(at, 1);
    },
  };
}

test('every listener it adds, it takes back off', () => {
  // The pad's host is the page's margin element, which OUTLIVES every layer
  // drawn on it — so a layer that went away without unbinding left a whole
  // listener set behind, and a page visited twice handled each stroke twice.
  const host = fakeHost();
  const unbind = bindHost(host, {
    pointerdown: () => {}, pointermove: () => {},
    pointerup: () => {}, pointercancel: () => {},
  });
  assert.equal(host.bound.length, 4);

  unbind();
  assert.deepEqual(host.bound, [], 'nothing left bound');
});

test('the same host bound and unbound many times accumulates nothing', () => {
  // One scroll-past per visit; a section read twice through visits each page
  // several times.
  const host = fakeHost();
  for (let visit = 0; visit < 10; visit += 1) {
    bindHost(host, { pointerdown: () => {}, pointerup: () => {} })();
  }
  assert.equal(host.bound.length, 0);
});

test('drawing turns native scrolling off, and giving up the host turns it back on', () => {
  // Left at 'none', a released margin becomes a strip the reader cannot
  // scroll the document from.
  const host = fakeHost('pan-y');
  const unbind = bindHost(host, { pointerdown: () => {} });
  assert.equal(host.style.touchAction, 'none');

  unbind();
  assert.equal(host.style.touchAction, 'pan-y', 'exactly what it was before');
});

test('the handlers bound are the ones handed over', () => {
  const host = fakeHost();
  const down = () => {};
  bindHost(host, { pointerdown: down });
  assert.deepEqual(host.bound, [['pointerdown', down]]);
});

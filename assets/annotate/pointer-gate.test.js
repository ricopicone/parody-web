import test from 'node:test';
import assert from 'node:assert/strict';
import { PointerGate, shouldBlockTouch } from './pointer-gate.js';

/** A touch event with the touch types Safari reports for each contact. */
function touchEvent(...types) {
  return { touches: types.map((touchType) => ({ touchType })) };
}

test('a finger does not draw', () => {
  // The whole report: a student swipes to scroll and gets a line instead.
  const gate = new PointerGate();
  assert.equal(gate.shouldDraw({ pointerType: 'touch' }), false);
});

test('a finger does not draw even before the pen has been seen', () => {
  // The old gate only stopped touch AFTER a pen had touched down, so the
  // first scroll of every session drew, and so did a palm that landed first.
  const gate = new PointerGate();
  assert.equal(gate.shouldDraw({ pointerType: 'touch' }), false);
  gate.shouldDraw({ pointerType: 'pen' });
  assert.equal(gate.shouldDraw({ pointerType: 'touch' }), false);
});

test('a stylus always draws', () => {
  assert.equal(new PointerGate().shouldDraw({ pointerType: 'pen' }), true);
});

test('a mouse always draws', () => {
  // A reader on a laptop has no stylus and never asked for one.
  assert.equal(new PointerGate().shouldDraw({ pointerType: 'mouse' }), true);
});

test('a finger draws when the reader has asked it to', () => {
  // The tablet with no stylus: the reader trades scrolling for drawing.
  const gate = new PointerGate({ fingerDraws: true });
  assert.equal(gate.shouldDraw({ pointerType: 'touch' }), true);
});

test('touch pans, which is what scroll and pinch-zoom are made of', () => {
  const gate = new PointerGate();
  assert.equal(gate.shouldPan({ pointerType: 'touch' }), true);
  assert.equal(gate.shouldPan({ pointerType: 'pen' }), false);

  gate.fingerDraws = true;
  assert.equal(gate.shouldPan({ pointerType: 'touch' }), false,
               'a finger being used as a pen is not also panning');
});

test('the touch-action a gate asks of its host', () => {
  // One-finger scrolling is the browser's; the two-finger gesture is ours,
  // because pinch drives the viewer's zoom rather than the browser's. The old
  // layer hardcoded 'none', which is why a finger could do neither.
  const gate = new PointerGate();
  assert.equal(gate.touchAction, 'pan-x pan-y');

  gate.fingerDraws = true;
  assert.equal(gate.touchAction, 'none');
});

test('a stylus gesture is cancelled so the page does not scroll under it', () => {
  // iOS decides scrolling from the TOUCH events, before any pointer event is
  // dispatched, so touch-action alone would let an Apple Pencil stroke scroll.
  assert.equal(shouldBlockTouch(touchEvent('stylus'), {}), true);
});

test('a finger gesture is left alone, which is how the page scrolls', () => {
  assert.equal(shouldBlockTouch(touchEvent('direct'), {}), false);
  assert.equal(shouldBlockTouch(touchEvent('direct', 'direct'), {}), false,
               'two fingers pinch-zoom');
});

test('a palm landing beside a live stroke cannot scroll the page', () => {
  // The ordering bug: a palm that touches down BEFORE the pen starts a native
  // scroll, and the stroke is then drawn against a moving page.
  assert.equal(shouldBlockTouch(touchEvent('direct'), { drawing: true }), true);
});

test('with finger drawing on, every gesture belongs to the ink', () => {
  assert.equal(shouldBlockTouch(touchEvent('direct'), { fingerDraws: true }), true);
});

test('a touch event with no touches at all is not a stylus', () => {
  assert.equal(shouldBlockTouch({}, {}), false);
});

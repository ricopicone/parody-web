/**
 * Which pointers draw, and which are left to the browser.
 *
 * A tablet reports a finger, a resting hand and the stylus as pointers of
 * different types, all arriving at the same element. The rule readers on
 * iPads asked for is the simple one: the stylus draws, and everything the
 * hand does — scrolling, pinching, resting — is the browser's business.
 *
 * The earlier rule was "touch draws until this session has seen a pen". It
 * meant the first swipe of every page load drew a line instead of scrolling,
 * a pinch drew two, and a palm that landed before the pen drew as well; the
 * gate only closed after the damage. Nothing is inferred now: touch draws
 * only when the reader has explicitly asked for it, which is the tablet with
 * no stylus at all.
 */
export class PointerGate {
  constructor({ fingerDraws = false } = {}) {
    this.fingerDraws = fingerDraws;
  }

  /** May this pointer draw? */
  shouldDraw(event) {
    if (event.pointerType === 'touch') return this.fingerDraws;
    return true;                       // pen, mouse, trackpad, anything else
  }

  /** May this pointer scroll/pinch the document instead? */
  shouldPan(event) {
    return event.pointerType === 'touch' && !this.fingerDraws;
  }

  /**
   * The touch-action an ink host must carry under this gate.
   *
   * 'pan-x pan-y' hands one-finger scrolling to the browser, which does it
   * better than we would, and keeps the two-finger gesture for ourselves:
   * pinch drives the viewer's own zoom (see pinch.js), because the browser's
   * pinch magnifies the whole application and takes the toolbar off-screen
   * with it. Saying 'manipulation' instead would let the browser have it.
   */
  get touchAction() {
    return this.fingerDraws ? 'none' : 'pan-x pan-y';
  }
}

/**
 * Whether a native touch gesture must be cancelled.
 *
 * touch-action is not enough on its own. iOS decides whether a gesture
 * scrolls from the TOUCH events, before any pointer event exists, and an
 * Apple Pencil arrives as a touch too (Safari marks it `touchType: 'stylus'`)
 * — so a stroke would scroll the page it is being drawn on. Cancelling the
 * gesture is the only way to say "this one is ink".
 *
 * `drawing` covers the palm that lands beside a live stroke: the gesture is
 * cancelled whether or not the stylus is still among the contacts, so a hand
 * settling on the glass cannot drag the page out from under the pen.
 */
export function shouldBlockTouch(event, { drawing = false,
                                          fingerDraws = false } = {}) {
  if (fingerDraws) return true;
  if (drawing) return true;
  return hasStylus(event);
}

function hasStylus(event) {
  const touches = event.touches || [];
  for (let i = 0; i < touches.length; i += 1) {
    if (touches[i].touchType === 'stylus') return true;
  }
  return false;
}

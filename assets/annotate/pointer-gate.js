/**
 * Palm rejection.
 *
 * A tablet reports the hand resting on the screen as ordinary touch pointers,
 * interleaved with the stylus. Heuristics on contact size are unreliable
 * across devices; the rule readers actually expect is simpler and needs no
 * guessing: once this session has seen a pen, touch stops drawing and goes
 * back to scrolling the document.
 *
 * Deliberately sticky. A stylus user who lifts the pen to scroll must not have
 * their palm start drawing again the moment the pen leaves range.
 */
export class PointerGate {
  constructor() {
    this.penSeen = false;
  }

  /** Record what kind of pointer this is. Call before shouldDraw. */
  note(event) {
    if (event.pointerType === 'pen') this.penSeen = true;
  }

  /** May this pointer draw? */
  shouldDraw(event) {
    if (event.pointerType === 'pen') return true;
    if (event.pointerType === 'touch') return !this.penSeen;
    return true;                       // mouse, trackpad, anything else
  }

  /** May this pointer scroll/pan the document instead? */
  shouldPan(event) {
    return event.pointerType === 'touch' && this.penSeen;
  }
}

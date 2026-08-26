/**
 * What the karaoke mark is currently showing, and what it still owes.
 *
 * The frame loop runs sixty times a second and the word changes perhaps three
 * times, so the mark has to remember what it has drawn or it repaints
 * constantly. The trap is remembering the wrong thing: the old code recorded
 * the word it was ABOUT to draw, before it knew whether it could.
 *
 * It often could not. The mark is only drawn on a page the viewer has
 * rasterised, and pdf.js rasterises asynchronously — so after any scroll or
 * seek there is a window in which the page exists, is on screen, and has no
 * canvas yet. Every word spoken in that window was recorded as painted and
 * then never drawn: skipped for its whole duration, and the mark did not
 * reappear until the voice moved on. That is the "skipping a lot of words"
 * report, and it is also why a tap on a word could seek correctly and leave
 * no mark behind.
 *
 * So: `needs` asks, `drew` is called only after something was actually put on
 * the page, and `invalidate` says the mark is no longer up — the layer was
 * destroyed, everything was cleared, or the page changed size under it.
 */
export class MarkState {
  constructor() {
    this.painted = -1;
  }

  /**
   * Does the mark owe this word a paint?
   *
   * `inEquation` overrides the memory: one display equation is a single word
   * with a single box, and the mark moves THROUGH it to show how far the
   * voice has got, so an unchanged word is not a reason to stop drawing.
   */
  needs(index, inEquation = false) {
    if (index < 0) return false;
    return inEquation || index !== this.painted;
  }

  /** Something was actually drawn for this word. Only then. */
  drew(index) {
    this.painted = index;
  }

  /** Whatever was up is not up any more. */
  invalidate() {
    this.painted = -1;
  }
}

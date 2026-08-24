/**
 * Keeping the spoken line on screen, without fighting the smooth scroll.
 *
 * `scrollTo({behavior: 'smooth'})` is an ANIMATION: it takes a few hundred
 * milliseconds, during which `scrollTop` is still short of the target. The
 * frame loop asks to follow on every frame, so asking again while it runs
 * re-issues the same journey 60 times a second — each call restarting the
 * animation from wherever it had got to, which is a scroll that crawls and
 * stutters and never arrives. It reads as the highlight lagging behind the
 * voice, and it was the whole of the "choppy" complaint.
 *
 * So the decision is remembered, not recomputed: a request is made only for a
 * destination meaningfully different from the last one asked for. A reader
 * scrolling by hand clears it, because their scroll is the new truth about
 * where the page should be.
 */
export class Follower {
  /** `slack` is how far the target must move to be worth a second request. */
  constructor({ slack = 1 / 3 } = {}) {
    this.slack = slack;
    this.requested = null;
  }

  /** A manual scroll, a seek, a new section: forget what we asked for. */
  reset() {
    this.requested = null;
  }

  /**
   * Whether to scroll, and to where. Null means leave the page alone.
   *
   * `top` is where the spoken line would sit centred; `scrollTop` and
   * `viewport` describe the scroller now.
   */
  target(top, scrollTop, viewport) {
    const reach = viewport * this.slack;
    // Already showing it: nothing to do, whatever we asked for before.
    if (Math.abs(scrollTop - top) <= reach) {
      this.requested = null;
      return null;
    }
    // A journey we have already asked for and which is still under way.
    if (this.requested !== null
        && Math.abs(this.requested - top) <= reach) {
      return null;
    }
    this.requested = top;
    return top;
  }
}

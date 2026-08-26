/**
 * Who owns the right to attach a rendered page.
 *
 * Rendering a PDF page is asynchronous and zoom cancels renders midway, which
 * makes this bookkeeping the fiddly part of the viewer — it produced two bugs
 * in a row when it lived inline: first a stale canvas attaching at the old
 * scale, then a blank page because a cancelled render still held the slot when
 * its replacement tried to start. It is a state machine, so it lives on its
 * own and is tested on its own.
 *
 * Two ideas:
 *   - a TOKEN identifies one render's claim, so a cancelled render cannot
 *     clear the state of the render that replaced it;
 *   - a GENERATION identifies the scale everything was started at, so work
 *     begun before a zoom is discarded rather than attached at the wrong size.
 */
/**
 * The scale everything is being drawn at.
 *
 * Shared by every page's slot: one page may render while another is cancelled,
 * but a zoom invalidates all of them at once.
 */
export class Generation {
  constructor() {
    this.value = 0;
  }

  bump() {
    this.value += 1;
    return this.value;
  }
}

export class RenderSlot {
  /** Pass a shared Generation so sibling pages invalidate together. */
  constructor(generation) {
    this.gen = generation || new Generation();
    this._token = 0;
    this.busy = false;
    this.owner = null;
  }

  get generation() {
    return this.gen.value;
  }

  /** A new scale. Everything in flight, on every page, is now stale. */
  invalidate() {
    return this.gen.bump();
  }

  /** Can a render start? False while one already owns the slot. */
  get free() {
    return !this.busy;
  }

  /** Take the slot. Returns the claim to pass back to finish/canFinish. */
  claim() {
    this._token += 1;
    this.busy = true;
    this.owner = this._token;
    return { token: this._token, generation: this.gen.value };
  }

  /**
   * Give the slot up immediately, without waiting for a cancellation to
   * settle. The replacement render runs synchronously after this.
   */
  release() {
    this.busy = false;
    this.owner = null;
  }

  /** A render finished. Clears the slot only if this claim still owns it. */
  finish(claim) {
    if (this.owner === claim.token) this.release();
  }

  /** May this claim attach what it drew? */
  canAttach(claim) {
    return claim.generation === this.gen.value;
  }

  /**
   * Has this claim been taken away since it started?
   *
   * Distinct from canAttach, which only asks about the SCALE. A page released
   * because the reader scrolled past it gives up its slot without bumping the
   * generation, so a render settling afterwards passes canAttach and would
   * announce a page that is no longer resident — building an ink layer that
   * the release which already ran can never pair with.
   *
   * Ask BEFORE finish(), which clears the ownership this reads.
   */
  superseded(claim) {
    return this.owner !== claim.token;
  }
}

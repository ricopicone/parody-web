/**
 * Which edits the server has: a count of edits made, and the count each
 * save carried.
 *
 * A finished save used to clear "unsaved" outright. A stroke drawn while
 * that save was in flight, still waiting out its debounce, then looked
 * saved: leaving for another translation went at once and the stroke never
 * reached the server, with no warning.
 */
export class Edits {
  constructor() {
    this.made = 0;
    this.saved = 0;
  }

  /** An edit the server does not have yet. */
  change() {
    this.made += 1;
  }

  /** A save is being built now: what it will carry. */
  stamp() {
    return this.made;
  }

  /** A save carrying `stamp` edits landed. */
  landed(stamp) {
    this.saved = Math.max(this.saved, stamp);
  }

  get unsaved() {
    return this.saved < this.made;
  }
}

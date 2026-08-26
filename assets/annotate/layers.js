/**
 * Which pages currently hold ink layers.
 *
 * A page's layers live exactly as long as its rendered canvas: PageView keeps
 * a window of pages around the viewport and releases the rest, and this
 * follows it. Before, nothing followed it — the map only ever grew, so a
 * scroll through a six-page section left twelve Konva stages alive for as long
 * as the tab was open. Measured in Chrome at dpr 2: 150 MB, because a stage
 * carries four canvases (the drawn one, its hit canvas, and two buffers), not
 * the one it appears to. That is what made annotating on an iPad get slower
 * the longer you read.
 *
 * Releasing is safe because a layer holds no state the store does not: the
 * strokes live in InkStore and `redraw()` rebuilds every path from it. A page
 * that comes back is built again from the same strokes.
 *
 * It lives on its own, like render-slot.js, because it is bookkeeping whose
 * failure is invisible: a leak looks exactly like working software.
 */
export class LayerSet {
  /** `build(entry)` returns the pair of layers for a page: { page, pad }. */
  constructor(build) {
    this.build = build;
    this.layers = new Map();
  }

  /** How many pages are resident. Over a whole read this must stay bounded. */
  get size() {
    return this.layers.size;
  }

  get(number) {
    return this.layers.get(number);
  }

  /** Visit the resident pages: `fn(pair, number)`. */
  forEach(fn) {
    this.layers.forEach(fn);
  }

  /**
   * The layers for this page, building them if it has none.
   *
   * `built` says which happened. A page is normally announced only after it
   * has been released, so it is nearly always true; false means the same page
   * was announced twice, and the caller must not orphan the layers the reader
   * may be drawing on right now.
   */
  ensure(entry) {
    const existing = this.layers.get(entry.number);
    if (existing) return { pair: existing, built: false };
    const pair = this.build(entry);
    this.layers.set(entry.number, pair);
    return { pair, built: true };
  }

  /** Give up this page's layers. False if it had none — the common case, as
   *  PageView releases every page outside the window on every scroll. */
  release(number) {
    const pair = this.layers.get(number);
    if (!pair) return false;
    // Out of the map first: destroy() must never be reachable twice, and a
    // half-destroyed pair must never be handed to forEach.
    this.layers.delete(number);
    pair.page.destroy();
    pair.pad.destroy();
    return true;
  }

  releaseAll() {
    for (const number of [...this.layers.keys()]) this.release(number);
  }
}

/**
 * The karaoke mark, one canvas per page above the pdf.js canvas.
 *
 * A canvas rather than positioned DOM: it repaints on one animation frame
 * without touching layout, which matters when it moves on every spoken word.
 *
 * Dark mode inverts the PAGE canvas through a CSS filter (see annotate.css).
 * This layer deliberately sits outside that filter, so its colour is chosen
 * for the theme here rather than being inverted along with the paper — an
 * inverted highlight comes out the complement of what was intended.
 */
import { toCss } from './reveal.js';

export class Highlight {
  /** `page` is {el, scale} from pageview.pageAt. */
  constructor(page, { dark = false } = {}) {
    this.page = page;
    this.dark = dark;
    this.canvas = document.createElement('canvas');
    this.canvas.className = 'readalong-highlight';
    page.el.appendChild(this.canvas);
    this.box = null;
    this.fit(page);
  }

  /**
   * Re-fit to the page, which changes size on zoom.
   *
   * Assigning `canvas.width` RESETS the drawing surface: it reallocates and
   * zeroes the entire backing store even when the value assigned is the one it
   * already had. This runs on every animation frame, because the page may have
   * been zoomed since the last one — so doing it unconditionally threw away
   * and rebuilt a 1620x2430 buffer sixty times a second at dpr 3, and
   * repainted the mark twice per frame into the bargain. Only a real change of
   * size may touch it.
   */
  fit(page) {
    this.page = page;
    const width = page.el.offsetWidth;
    const height = page.el.offsetHeight;
    const dpr = (typeof window !== 'undefined' && window.devicePixelRatio) || 1;
    if (this.ctx && width === this.cssWidth && height === this.cssHeight
        && dpr === this.dpr) {
      return;
    }
    this.cssWidth = width;
    this.cssHeight = height;
    this.dpr = dpr;
    this.canvas.width = Math.floor(width * dpr);
    this.canvas.height = Math.floor(height * dpr);
    this.canvas.style.width = `${width}px`;
    this.canvas.style.height = `${height}px`;
    this.ctx = this.canvas.getContext('2d');
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (this.box) this._paint();
  }

  setDark(dark) {
    this.dark = dark;
    if (this.box) this._paint();
  }

  /**
   * `box` is [x0, y0, x1, y1] in PDF points.
   *
   * A word lasts a few hundred milliseconds — a dozen frames or more — and the
   * mark does not move for any of them. Repainting anyway is pure waste, so a
   * box identical to the one already up is nothing to do.
   */
  show(box) {
    if (this.box && same(this.box, box)) return;
    this.box = box;
    this._paint();
  }

  _paint() {
    const { x0, y0, x1, y1 } = toCss(this.box, this.page.scale);
    this._wipe();
    this.ctx.fillStyle = this.dark
      ? 'rgba(255, 214, 102, 0.26)'
      : 'rgba(255, 214, 102, 0.52)';
    // A touch of bleed so descenders and the leading are covered evenly.
    this.ctx.fillRect(x0 - 1, y0 - 1, x1 - x0 + 2, y1 - y0 + 2);
  }

  clear() {
    this.box = null;
    this._wipe();
  }

  _wipe() {
    this.ctx.clearRect(0, 0, this.canvas.width / this.dpr,
                       this.canvas.height / this.dpr);
  }

  destroy() {
    this.canvas.remove();
  }
}

function same(a, b) {
  return a[0] === b[0] && a[1] === b[1] && a[2] === b[2] && a[3] === b[3];
}

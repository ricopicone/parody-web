/**
 * Making the blanks findable.
 *
 * A blank is a ruled gap in a typeset page, which is exactly what a typeset
 * page is full of — rules under headings, table borders, the gaps around
 * displayed equations. Scrolling to find them does not work; the reader has
 * to already know where they are.
 *
 * So: every blank on a rendered page carries a persistent marker, and a small
 * navigator steps between them. Neither depends on playback — finding the
 * blanks is what you do BEFORE you start, or when you come back to finish.
 */

/** Blanks on one page, in reading order. */
export function blanksOnPage(clozes, page) {
  return (clozes || []).filter((c) => c.page === page);
}

/**
 * The blank after `index`, wrapping to the first. Returns -1 when there are
 * none at all, so the navigator can hide itself rather than sit there inert.
 */
export function nextBlank(clozes, index, direction = 1) {
  const count = (clozes || []).length;
  if (!count) return -1;
  // "Nowhere" is not position -1 to be stepped from: from a standing start,
  // forward means the first blank and back means the last.
  if (index < 0) return direction > 0 ? 0 : count - 1;
  return ((index + direction) % count + count) % count;
}

/** A percentage of the page box, tidied so it does not read as noise. */
const pct = (value) => `${Math.round(value * 1e4) / 1e4}%`;

/**
 * The blank outlines on one page.
 *
 * One positioned element per blank, NOT a canvas. A canvas here was a
 * full-page backing store — 7 MB at dpr 2, 16 MB at dpr 3 — carrying a
 * handful of small rectangles, and there was one for every page in the
 * section that has a blank, all at once: syncMarks wants them on placeholder
 * pages too (finding the blanks is what a reader does BEFORE pressing play),
 * and every page element exists from the moment the document opens. Measured
 * on a three-page section: 20 MB of 33 MB. There is no window to shrink it
 * to without giving up the thing the marks are for.
 *
 * Positions are PERCENTAGES of the page box, which is what makes this cheaper
 * than the canvas rather than merely smaller: a page laid out at
 * `pageWidthPt * scale` puts a blank at the same percentage at every zoom, so
 * following a zoom costs nothing at all. The canvas had to reallocate its
 * whole surface and repaint every mark.
 *
 * Kept as its own layer rather than folded into the karaoke canvas: that one
 * is cleared and repainted on every spoken word, and these marks have to
 * persist while the reader scrolls around with nothing playing.
 */
export class BlankMarks {
  constructor(page, { dark = false } = {}) {
    this.page = page;
    this.dark = dark;
    this.host = document.createElement('div');
    this.host.className = 'readalong-blanks';
    this.host.dataset.dark = dark ? '1' : '0';
    page.el.appendChild(this.host);
    this.boxes = [];
    this.nodes = [];
    this.active = -1;
    this.placed = false;
  }

  /**
   * Follow the page.
   *
   * Runs on every scroll event and on the marker timer, and does nothing in
   * the common case — which is the point. It has work only when the marks
   * have never been placed, because the page had no size the first time
   * round: syncMarks builds a layer the moment the page ELEMENT exists, which
   * can be before it has been laid out.
   */
  fit(page) {
    this.page = page;
    if (!this.placed) this._place();
  }

  /** `boxes` are {token, kind, x0, y0, x1, y1} in PDF points. */
  setBoxes(boxes) {
    this.boxes = boxes || [];
    this.host.replaceChildren();
    this.nodes = this.boxes.map((box) => {
      const node = document.createElement('div');
      node.className = 'readalong-blank';
      // A blank inside an EQUATION is marked by its equation, because the
      // rules within one are a mix of blanks and fraction bars and telling
      // them apart is a problem we do not take on. That box is the whole
      // derivation — up to 180 points tall — so the stylesheet outlines it
      // rather than washing over it: a fill there is a slab of colour across
      // the maths and reads as a fault, where the wash over a one-line blank
      // reads as a space to write in.
      node.dataset.kind = box.kind === 'math_cloze' ? 'math_cloze' : 'cloze';
      node.dataset.on = box.token === this.active ? '1' : '0';
      this.host.appendChild(node);
      return node;
    });
    this.placed = false;
    this._place();
  }

  setActive(token) {
    // Called from the marker sync, which runs on every scroll event: a smooth
    // scroll would otherwise touch every blank on every page, 60 times a
    // second, to arrive at the same picture.
    if (token === this.active) return;
    this.active = token;
    this.boxes.forEach((box, index) => {
      const node = this.nodes[index];
      if (node) node.dataset.on = box.token === token ? '1' : '0';
    });
  }

  setDark(dark) {
    if (dark === this.dark) return;
    this.dark = dark;
    // One attribute. The colours are the stylesheet's, so nothing is redrawn.
    this.host.dataset.dark = dark ? '1' : '0';
  }

  /** Place every mark as a percentage of the page box. False until the page
   *  has a size to take a percentage of. */
  _place() {
    const { el, scale } = this.page;
    const width = el.offsetWidth;
    const height = el.offsetHeight;
    if (!(width > 0 && height > 0 && scale > 0)) return false;
    const widthPt = width / scale;
    const heightPt = height / scale;
    this.boxes.forEach((box, index) => {
      const node = this.nodes[index];
      if (!node) return;
      const x0 = Math.min(box.x0, box.x1);
      const x1 = Math.max(box.x0, box.x1);
      const y0 = Math.min(box.y0, box.y1);
      const y1 = Math.max(box.y0, box.y1);
      node.style.left = pct(x0 / widthPt * 100);
      node.style.top = pct(y0 / heightPt * 100);
      node.style.width = pct((x1 - x0) / widthPt * 100);
      node.style.height = pct((y1 - y0) / heightPt * 100);
    });
    this.placed = true;
    return true;
  }

  destroy() {
    this.host.remove();
  }
}

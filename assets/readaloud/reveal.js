/**
 * The answer, shown so it can be copied.
 *
 * ABOVE the blank, never in it. The blank is where the student writes and the
 * annotation canvas is live over it, so a plate in the blank would simply be
 * drawn on top of. Above rather than below because a stylus hand rests below
 * the line being written, so a plate below is the one that ends up under the
 * palm — and because reading up then writing down is the movement you want.
 *
 * It holds until the student continues rather than fading on a timer: this is
 * the board in class, and it stays up while you write it down.
 */
const GAP = 6;          // clear space between plate and blank, in CSS px

/**
 * A PDF-point box to CSS pixels within a rendered page element.
 *
 * No y-flip and no pdf.js viewport: PyMuPDF reports boxes with a top-left
 * origin, which is the DOM's convention already, and the page is rendered at
 * `pageWidthPt * scale`. Deriving the scale from the element keeps this bundle
 * independent of the annotator's — the two ship separately and must not share
 * live objects.
 */
export function toCss(box, scale) {
  const [ax, ay, bx, by] = box;
  return {
    x0: Math.min(ax, bx) * scale,
    y0: Math.min(ay, by) * scale,
    x1: Math.max(ax, bx) * scale,
    y1: Math.max(ay, by) * scale,
  };
}

/**
 * Where to put the plate, given the blank's box in PDF points.
 * `plate` is {width, height} in CSS px.
 */
export function placeReveal(box, scale, plate) {
  const { x0, y0, x1, y1 } = toCss(box, scale);
  const left = (x0 + x1) / 2 - plate.width / 2;
  let top = y0 - plate.height - GAP;
  // Flip below when there is no room above, so a blank on the first line
  // never renders off the top of the page.
  if (top < 0) top = y1 + GAP;
  return { left, top };
}

export class Reveal {
  constructor() {
    this.el = document.createElement('div');
    this.el.className = 'readalong-reveal';
    this.el.hidden = true;
  }

  /** `page` is {el, pad, scale} — see pageview.js. */
  show(cloze, page) {
    return cloze.kind === 'figure_cloze'
      ? this._showFigure(cloze, page)
      : this._showText(cloze, page);
  }

  _showText(cloze, page) {
    this.el.dataset.kind = 'text';
    this.el.textContent = cloze.answer;
    this.el.hidden = false;
    this.el.classList.remove('is-fading');
    page.el.appendChild(this.el);
    // Measure after attaching: the plate's width depends on the answer.
    const plate = { width: this.el.offsetWidth, height: this.el.offsetHeight };
    const at = placeReveal([cloze.x0, cloze.y0, cloze.x1, cloze.y1],
                           page.scale, plate);
    this.el.style.left = `${at.left}px`;
    this.el.style.top = `${at.top}px`;
    return this.el;
  }

  /**
   * Figure clozes reveal into the margin pad: the complete artwork must not
   * cover the incomplete figure the student is drawing into, and the pad is
   * half a page wide and immediately adjacent.
   *
   * This is a transient overlay child of the pad, never pad *content* — the
   * exporter glues a reader's pad strokes onto the page, and must not find
   * this among them.
   */
  _showFigure(cloze, page) {
    this.el.dataset.kind = 'figure';
    this.el.innerHTML = '';
    const img = document.createElement('img');
    img.src = cloze.src;
    img.alt = '';
    this.el.appendChild(img);
    this.el.hidden = false;
    this.el.classList.remove('is-fading');
    const host = page.pad || page.el;
    host.appendChild(this.el);
    const { y0 } = toCss([cloze.x0, cloze.y0, cloze.x1, cloze.y1], page.scale);
    this.el.style.left = '0px';
    this.el.style.top = `${y0}px`;
    return this.el;
  }

  fade() {
    if (this.el.hidden) return;
    this.el.classList.add('is-fading');
    const done = () => { this.el.hidden = true; };
    this.el.addEventListener('transitionend', done, { once: true });
    // A background tab fires no transitions, so the plate would never hide.
    setTimeout(done, 1200);
  }

  destroy() {
    this.el.remove();
  }
}

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

/**
 * A canvas of blank outlines, one per page.
 *
 * Its own layer rather than a second use of the karaoke canvas: that one is
 * cleared and repainted on every spoken word, and these marks have to persist
 * while the reader scrolls around with nothing playing at all.
 */
export class BlankMarks {
  constructor(page, { dark = false } = {}) {
    this.page = page;
    this.dark = dark;
    this.canvas = document.createElement('canvas');
    this.canvas.className = 'readalong-blanks';
    page.el.appendChild(this.canvas);
    this.boxes = [];
    this.active = -1;
    this.fit(page);
  }

  /**
   * Re-fit to the page. Runs on every scroll event and on the marker timer,
   * so it must be free when nothing has actually changed: assigning
   * `canvas.width` reallocates and zeroes the whole backing store even when
   * the value is unchanged, and a smooth scroll fires scroll every frame.
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
    this.draw();
  }

  /** `boxes` are {token, x0, y0, x1, y1} in PDF points. */
  setBoxes(boxes) {
    this.boxes = boxes || [];
    this.draw();
  }

  setActive(token) {
    // Called from the marker sync, which runs on every scroll event: a smooth
    // scroll would otherwise redraw every blank on every page, 60 times a
    // second, to arrive at the same picture.
    if (token === this.active) return;
    this.active = token;
    this.draw();
  }

  setDark(dark) {
    if (dark === this.dark) return;
    this.dark = dark;
    this.draw();
  }

  draw() {
    if (!this.ctx) return;
    const { scale } = this.page;
    this.ctx.clearRect(0, 0, this.canvas.width / this.dpr,
                       this.canvas.height / this.dpr);
    for (const box of this.boxes) {
      const x0 = Math.min(box.x0, box.x1) * scale;
      const x1 = Math.max(box.x0, box.x1) * scale;
      const y0 = Math.min(box.y0, box.y1) * scale;
      const y1 = Math.max(box.y0, box.y1) * scale;
      const on = box.token === this.active;
      const pad = 3;

      // A blank inside an EQUATION is marked by its equation, because the
      // rules within one are a mix of blanks and fraction bars and telling
      // them apart is a problem we do not take on. That box is the whole
      // derivation — up to 180 points tall — so it gets an outline rather than
      // a wash: filling it would put a slab of colour over the maths and read
      // as a fault, where the wash over a one-line blank reads as a space to
      // write in.
      if (box.kind === 'math_cloze') {
        this.ctx.strokeStyle = this.dark
          ? `rgba(122, 184, 255, ${on ? 0.85 : 0.35})`
          : `rgba(66, 133, 244, ${on ? 0.8 : 0.3})`;
        this.ctx.lineWidth = on ? 1.5 : 1;
        this.ctx.strokeRect(x0 - pad, y0 - pad,
                            x1 - x0 + pad * 2, y1 - y0 + pad * 2);
        continue;
      }

      // A soft wash over the writing space, and a firmer edge on the one the
      // navigator just moved to. Deliberately weak: the reader is going to
      // write here, and a heavy box would fight their own handwriting.
      this.ctx.fillStyle = this.dark
        ? `rgba(122, 184, 255, ${on ? 0.22 : 0.10})`
        : `rgba(66, 133, 244, ${on ? 0.20 : 0.09})`;
      this.ctx.fillRect(x0 - pad, y0 - pad,
                        x1 - x0 + pad * 2, y1 - y0 + pad * 2);

      if (on) {
        this.ctx.strokeStyle = this.dark
          ? 'rgba(122, 184, 255, 0.85)'
          : 'rgba(66, 133, 244, 0.8)';
        this.ctx.lineWidth = 1.5;
        this.ctx.strokeRect(x0 - pad, y0 - pad,
                            x1 - x0 + pad * 2, y1 - y0 + pad * 2);
      }
    }
  }

  destroy() {
    this.canvas.remove();
  }
}

/**
 * Coordinates for ink on a paged document.
 *
 * The old notebook-drawing engine anchored strokes to viewport coordinates
 * over reflowing HTML, and compensated by shifting every stroke when the prose
 * container moved. That cannot survive a rewrap, which is why those marks were
 * good for a session and useless as notes.
 *
 * A PDF page does not reflow. These functions map a pointer to a fixed point
 * on a fixed page, in PDF points, and that is what makes the ink permanent.
 *
 * Pure functions, no DOM, so they can be tested without a browser.
 */

/**
 * Client (CSS pixel) offset within a rendered page → PDF points.
 *
 * Device pixel ratio deliberately does not appear: DPR belongs to the canvas
 * backing store, not to the document. Letting it reach this function would
 * make a reader's ink land differently on a retina screen.
 */
export function screenToPdf(offsetX, offsetY, viewport) {
  const scale = viewport.scale || 1;
  return { x: offsetX / scale, y: offsetY / scale };
}

/** PDF points → CSS pixels within the rendered page. */
export function pdfToScreen(x, y, viewport) {
  const scale = viewport.scale || 1;
  return { x: x * scale, y: y * scale };
}

/**
 * A pointer transform for one page, in the shape pointer-utils.setPointerTransform
 * expects. `rectOf` returns the page element's bounding rect; it is injected so
 * this stays testable.
 */
export function pagedTransform(pageNumber, viewport, rectOf) {
  return (event) => {
    const rect = rectOf();
    const local = screenToPdf(event.clientX - rect.left,
                              event.clientY - rect.top, viewport);
    return {
      page: pageNumber,
      x: local.x,
      y: local.y,
      pressure: event.pressure > 0 ? event.pressure : 0.5,
    };
  };
}

/**
 * Which page a scroll position is nearest, for windowed rendering.
 * `tops` are page offsets in document order.
 */
export function pageAt(scrollTop, tops) {
  let current = 0;
  for (let i = 0; i < tops.length; i += 1) {
    if (tops[i] <= scrollTop) current = i;
    else break;
  }
  return current;
}

/** Indices to keep rendered around `page`; everything else is released. */
export function windowAround(page, count, radius = 1) {
  const pages = [];
  for (let i = Math.max(0, page - radius);
       i <= Math.min(count - 1, page + radius); i += 1) {
    pages.push(i);
  }
  return pages;
}

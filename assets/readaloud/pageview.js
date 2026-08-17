/**
 * Finding the annotator's pages from outside its bundle.
 *
 * Read-along ships as its own bundle, so it cannot hold a reference to the
 * annotator's PageView. It does not need one: the annotator marks each page
 * element with `data-page`, and the page is laid out at `pageWidthPt * scale`,
 * so the scale is recoverable from the element's own width. That keeps the two
 * bundles independent — they are versioned and loaded separately, and a shared
 * live object between them would be a silent coupling.
 *
 * `pageSizes` comes from the track payload: [[widthPt, heightPt], ...].
 */
export function pageAt(root, number, pageSizes) {
  const el = root.querySelector(`.ink-page[data-page="${number + 1}"]`);
  if (!el) return null;                 // canvas released, or not rendered yet
  const size = (pageSizes || [])[number];
  const widthPt = size && size[0];
  const rendered = el.offsetWidth || parseFloat(el.style.width) || 0;
  if (!widthPt || !rendered) return null;
  return {
    el,
    pad: el.parentElement
      ? el.parentElement.querySelector('.ink-pad')
      : null,
    scale: rendered / widthPt,
  };
}

/**
 * Whether a page is currently rendered, as opposed to a bare placeholder.
 *
 * The annotator keeps canvases for only about three pages at a time, so a page
 * element can exist with nothing drawn on it. Highlighting such a page draws a
 * mark over blank paper.
 */
export function isRendered(page) {
  return !!(page && page.el.querySelector('canvas.ink-page-canvas'));
}

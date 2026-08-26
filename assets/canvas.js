/**
 * Giving a canvas's pixels back.
 *
 * `canvas.remove()` only DETACHES it. The backing store — width x height x 4
 * bytes, and a page canvas at dpr 3 is 16 MB of it — stays allocated until
 * the element is collected, which on a tablet is the whole cost of the thing.
 * Zeroing the dimensions frees it there and then. This is exactly what Konva
 * does in Util.releaseCanvas, and it is why stage.destroy() returns memory
 * while a hand-rolled `.remove()` does not.
 *
 * Measured on task #675: ten blank-marker layers destroyed with `.remove()`
 * left all 66.7 MB of them still allocated.
 *
 * Shared by both bundles because it is one rule, not two. They stay separate
 * at runtime — each gets its own copy inlined.
 */
export function releaseCanvas(canvas) {
  if (!canvas) return;
  canvas.remove();
  // Order matters only for tidiness; both are needed. A canvas that is still
  // in the document when this runs is detached first so nothing repaints it
  // at zero size.
  canvas.width = 0;
  canvas.height = 0;
}

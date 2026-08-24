/**
 * The page's body type size, in points, measured off the page itself.
 *
 * The reveal is sized to the page rather than to the browser, so a zoomed-in
 * reader gets an answer the size the answer would have been printed. There is
 * no font metadata to ask — the geometry is a list of word boxes — so the size
 * comes from the median box height. A box spans ascender to descender and so
 * runs about half again the type size; BOX_TO_TYPE brings it back.
 *
 * PROSE boxes only, and that qualifier is the whole subtlety. A display
 * equation is ONE token, so every word of its narration carries the same box —
 * the one spanning the entire derivation, which can be 180 points tall. In an
 * equation-dense section those words outnumber the prose, so a median over all
 * of them lands on an equation's height and reveals the answer at three times
 * the size of the page around it. A cloze's box is its RULE, a hairline, and
 * drags the median the other way just as wrongly.
 */
const BOX_TO_TYPE = 0.66;
const FALLBACK_PT = 15 * BOX_TO_TYPE;

export function bodyType(track) {
  const words = (track && track.words) || [];
  const maths = new Set(((track && track.regions) || []).map((r) => r.token));
  const clozes = new Set(((track && track.clozes) || []).map((c) => c.token));

  const heights = (keep) => words
    .filter((w) => Number.isFinite(w.y0) && Number.isFinite(w.y1) && keep(w))
    .map((w) => w.y1 - w.y0)
    .sort((a, b) => a - b);

  const prose = heights((w) => !maths.has(w.token) && !clozes.has(w.token));
  // A section that is nothing but equations has no prose to measure. Any boxed
  // word is a better guess than a constant, and the constant is the last word.
  const list = prose.length ? prose : heights(() => true);
  if (!list.length) return FALLBACK_PT;
  return list[Math.floor(list.length / 2)] * BOX_TO_TYPE;
}

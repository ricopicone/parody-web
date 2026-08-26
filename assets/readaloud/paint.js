/**
 * One word's worth of decisions: where to send the page, and what to draw.
 *
 * Extracted from the frame loop because the ORDER of these steps is the whole
 * of it, and getting it wrong is invisible — it looks like a highlight that
 * skips, not like broken logic. It had been wrong in two different ways.
 *
 * The rule that matters: THE PAGE MUST FOLLOW THE VOICE WHETHER OR NOT THERE
 * IS ANYTHING TO DRAW THERE YET.
 *
 * follow() used to sit below the layer lookup, which made the three facts
 * below into a deadlock:
 *
 *   - a word is only drawn on a page pdf.js has rasterised;
 *   - a page is only rasterised while it is near the VIEWPORT;
 *   - the viewport only moved to the voice once the word had been drawn.
 *
 * So the moment the voice passed the far edge of the rendered window, the page
 * stopped following it — and therefore never rendered the page it had moved
 * on to, and therefore never drew, and therefore never followed. Nothing
 * short of pressing play again broke the cycle. Measured on a live section:
 * walking the voice through all 487 words asked the page to scroll twice, and
 * never once for a page that had not already rendered.
 *
 * Following needs no canvas. The viewer lays every page out at its true size
 * from the moment the document opens — that is what makes the scrollbar
 * honest — so `findPage` answers for a bare placeholder, and its offset and
 * scale are all a scroll needs.
 */

/**
 * Returns what happened, for the caller and for the tests:
 * 'unchanged' | 'no-box' | 'unrendered' | 'painted'.
 */
export function paintWord(word, index, {
  mark, inEquation = false, findPage, findLayer, follow, draw,
}) {
  // The frame loop runs sixty times a second and the word changes perhaps
  // three; re-deciding on every frame is what made the smooth scroll restart
  // constantly and crawl.
  if (!mark.needs(index, inEquation)) return 'unchanged';

  // No box anywhere in the document: it can never be drawn and there is
  // nowhere to travel to, so stop asking about it.
  if (!Number.isFinite(word.page)) {
    mark.drew(index);
    return 'no-box';
  }

  // BEFORE the layer, always. See above.
  const page = findPage(word.page);
  if (page) follow(page, word);

  const layer = findLayer(word.page);
  // The page has no canvas yet — pdf.js rasterises asynchronously, so there is
  // a window after every scroll and every seek where the page is on screen
  // with nothing drawn on it. Nothing was painted, so nothing is remembered:
  // the mark is still owed and the next frame tries again. Recording it here
  // is what skipped the word for its whole duration.
  if (!layer) return 'unrendered';

  draw(layer, word);
  mark.drew(index);
  return 'painted';
}

/**
 * Reading the timing array.
 *
 * Timings are sorted and non-overlapping, so the word lookup is a binary
 * search: it runs on every animation frame, and a linear scan over a section's
 * few thousand words is enough to drop frames on a tablet.
 */

/** Index of the word being spoken at `ms`, or -1. */
export function wordAt(words, ms) {
  let low = 0;
  let high = words.length - 1;
  while (low <= high) {
    const mid = (low + high) >> 1;
    const word = words[mid];
    if (ms < word.start_ms) high = mid - 1;
    else if (ms >= word.end_ms) low = mid + 1;
    else return mid;
  }
  return -1;
}

/**
 * Index of the cloze being SPOKEN at `ms`, or -1.
 *
 * The reveal follows the voice: the answer appears as it is read, not after.
 * Hearing a term and only then seeing it made the two feel unrelated.
 */
export function revealAt(clozes, ms) {
  for (let i = 0; i < (clozes || []).length; i += 1) {
    if (ms >= clozes[i].start_ms && ms < clozes[i].end_ms) return i;
  }
  return -1;
}

/**
 * Index of the cloze whose answer has finished, or -1 — where playback stops.
 *
 * Still `end_ms`: the reveal appears with the voice, but the pause waits until
 * the whole term has been said rather than cutting it off mid-word.
 */
export function clozeAt(clozes, ms) {
  let due = -1;
  for (let i = 0; i < clozes.length; i += 1) {
    if (ms >= clozes[i].end_ms) due = i;
    else break;
  }
  return due;
}

/** Clozes with a box, in page order — the ones the client can actually show. */
export function showable(clozes) {
  return (clozes || []).filter((c) => Number.isFinite(c.x0)
                                   && Number.isFinite(c.page));
}

/**
 * The maths region being spoken at `ms`, or null.
 *
 * Regions are short and few — a handful per section against thousands of
 * words — so a scan is fine here where the word lookup needed a binary search.
 */
export function regionAt(regions, ms) {
  for (const region of regions || []) {
    if (ms >= region.start_ms && ms < region.end_ms) return region;
  }
  return null;
}

/**
 * Where skipping should land, from `ms`.
 *
 * Inside a spoken equation, the end of it — SRE is verbose by necessity and a
 * reader who has taken the point should not have to sit through the rest.
 * Anywhere else, the start of the next sentence. Skip is offered ALWAYS, not
 * only over maths: wanting to move on is not a thing that only happens during
 * an equation.
 */
export function skipTarget(regions, ms, words, reachMs = 1500) {
  const here = regionAt(regions, ms);
  if (here) return here.end_ms;

  // A maths region about to start counts as "here" — pressing skip as the
  // equation begins is the common case.
  let soon = null;
  for (const region of regions || []) {
    if (region.start_ms >= ms && region.start_ms - ms <= reachMs) {
      if (!soon || region.start_ms < soon.start_ms) soon = region;
    }
  }
  if (soon) return soon.end_ms;

  return nextSentence(words, ms);
}

/** The start of the next sentence after `ms`, or null at the last one. */
export function nextSentence(words, ms) {
  const list = words || [];
  let seenCurrent = false;
  for (let i = 0; i < list.length; i += 1) {
    if (!seenCurrent) {
      if (list[i].end_ms > ms) seenCurrent = true;
      else continue;
    }
    // The word AFTER a sentence-ending one begins the next sentence.
    if (i > 0 && /[.?!]["')\]]?$/.test(list[i - 1].word || '')
        && list[i].start_ms > ms) {
      return list[i].start_ms;
    }
  }
  return null;
}

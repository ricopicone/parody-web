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
 * Index of the cloze that is due at `ms`, or -1.
 *
 * Due at `end_ms`, not `start_ms`: the answer is spoken first and the reveal
 * holds afterwards, so the pause lands once the student has heard the whole
 * term rather than cutting them off mid-word.
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
 * Where skipping should land: the end of the maths being spoken now, or the
 * start of the next one if we are between them and it is close enough to be
 * what the reader meant. Null when there is nothing to skip.
 */
export function skipTarget(regions, ms, reachMs = 1500) {
  const here = regionAt(regions, ms);
  if (here) return here.end_ms;
  let best = null;
  for (const region of regions || []) {
    if (region.start_ms >= ms && region.start_ms - ms <= reachMs) {
      if (!best || region.start_ms < best.start_ms) best = region;
    }
  }
  return best ? best.end_ms : null;
}

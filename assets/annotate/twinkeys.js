/**
 * Which translated pages a reader's ink on a translation was written over.
 *
 * The server keys each language's ink with the pages beside the English when
 * it was written (parody_web.printing.twin_paired_key). A translation can be
 * rebuilt against the same English — a retranslation, a fix to how its pages
 * were cut — and then those notes sit over other text. Nothing moves them;
 * the reader is told, and the key moves on only once they write on the new
 * pages, so a stroke on the English cannot quietly clear the warning.
 */

/** Was the ink on `language` written over other pages than those shown? */
export function twinIsStale(loadedKeys, language, currentKey, hasInk) {
  const was = (loadedKeys || {})[language];
  return !!(language && hasInk && was && currentKey && was !== currentKey);
}

/** The keys to save with the ink. */
export function keysToSave(loadedKeys, language, currentKey, { hadInk, touched }) {
  const keys = { ...(loadedKeys || {}) };
  if (language && currentKey && (!hadInk || touched)) keys[language] = currentKey;
  return keys;
}

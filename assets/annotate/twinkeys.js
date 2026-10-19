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

/**
 * The key to send with the ink: the shown language's, when it moves on, else
 * nothing. The server replaces each language's key it is sent and keeps the
 * rest, so not sending is how a key stays as it was.
 */
export function keysToSend(loadedKeys, language, currentKey, { hadInk, touched }) {
  if (language && currentKey && (!hadInk || touched)) return { [language]: currentKey };
  return undefined;
}

/**
 * The translation ink to send: the language shown only, empty when every
 * stroke on it was erased (so the server clears it), and none at all without
 * a translation on screen. The server keeps every language not sent; sending
 * all the languages loaded let a tab opened earlier erase notes written since.
 */
export function twinInkToSend(allTwins, language) {
  if (!language) return undefined;
  return { [language]: (allTwins || {})[language] || {} };
}

/**
 * Whether the reader has dismissed the "translation changed" notice for this
 * section, language and translation. Only a later change brings it back: OK
 * used to remove it from the page alone, so it returned on every visit.
 * Browser storage is a convenience here; refused (private mode), the notice
 * just shows again.
 */
const noticeKey = (path, language, key) => `parody-twin-notice:${path}:${language}:${key}`;

export function noticeDismissed(storage, path, language, key) {
  try {
    return storage.getItem(noticeKey(path, language, key)) === '1';
  } catch (err) {
    return false;
  }
}

export function dismissNotice(storage, path, language, key) {
  try {
    storage.setItem(noticeKey(path, language, key), '1');
  } catch (err) { /* private mode: it shows again next time */ }
}

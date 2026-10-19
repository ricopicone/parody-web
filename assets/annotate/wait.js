/**
 * Waiting for the translation, but not for ever.
 *
 * The English is drawn once both PDFs have opened, so a translation that
 * stalls (a phone on a slow connection, a first request that cuts the paired
 * PDF) would leave the English blank too. A translation that has not opened
 * in time is given up: the reader gets the English, and a word that the
 * translation did not load.
 */

/** How long the English waits for the translation, in milliseconds. */
export const TWIN_WAIT_MS = 8000;

/**
 * `promise`'s value if it settles within `ms`, else null, calling
 * `letGo` so whatever it was loading can be stopped.
 */
export function within(promise, ms, letGo = () => {}) {
  let timer;
  const late = new Promise((resolve) => {
    timer = setTimeout(() => {
      letGo();
      resolve(null);
    }, ms);
  });
  return Promise.race([promise.finally(() => clearTimeout(timer)), late]);
}

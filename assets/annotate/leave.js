/**
 * Leaving the page for another view of it — another translation, English
 * only, another version — after the reader's notes are saved.
 *
 * Each of those is a page load. Right after a stroke the save was still in
 * flight as the page unloaded, so the browser asked "Leave site?" of a reader
 * who had only switched translation. Saving first, then going, keeps that
 * question for a save that actually failed: beforeunload still asks then.
 */
export async function leaveAfterSaving(href, { unsaved, saveNow, go, waitMs = 3000 }) {
  // Never longer than waitMs: with the server unreachable the link would
  // seem to do nothing. beforeunload still warns of what did not land.
  if (unsaved()) await Promise.race([saveNow(), new Promise((r) => setTimeout(r, waitMs))]);
  go(href);
}

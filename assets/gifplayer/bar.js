/**
 * The control bar's decisions, kept out of index.js so `node --test` can
 * check them without a DOM: which action a key means, how the bar shows a
 * state, what a batch of IntersectionObserver entries says, and where an
 * author's width goes.
 */

const KEYS = {
  ' ': 'toggle', k: 'toggle', K: 'toggle',
  ArrowLeft: 'back', PageUp: 'back',
  ArrowRight: 'next', PageDown: 'next', // presentation clickers send these
  Home: 'first', End: 'last',
  f: 'full', F: 'full',
};

// keys a focused control already answers the same way natively. Not
// PageUp/PageDown on the scrubber: a range input moves 10% for them, and
// PageDown backwards, so a clicker would jump frames the wrong way.
const NATIVE = {
  BUTTON: new Set([' ', 'Enter']),
  INPUT: new Set(['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End']),
};

// keys that act once however long they are held. A held key repeats about ten
// times a second: play/pause would flicker and full screen would thrash. A
// held arrow is left to repeat, which steps through the frames.
const ONCE = new Set(['toggle', 'full']);

/** The player action a keydown means, or null to leave it to the browser.
 * 'held' is a repeat of a key that acts once: still the player's key (so a
 * held Space does not scroll the page), but it does nothing. */
export function keyAction(e) {
  if (e.altKey || e.ctrlKey || e.metaKey) return null;
  const name = KEYS[e.key];
  if (!name) return null;
  const native = NATIVE[e.target && e.target.tagName];
  if (native && native.has(e.key)) return null;
  if (e.repeat && ONCE.has(name)) return 'held';
  return name;
}

/** A function that shows a controller state on the bar's elements.
 *
 * The play button is touched only when playing/paused changes. Frames change
 * every 50 ms, and replacing the <svg> under a pressed mouse button cancels
 * the click (Chromium drops a click whose mousedown node left the tree), so
 * rewriting it per frame made Pause all but unclickable with a mouse. */
export function barView({ play, scrub, count }, n, icons) {
  // as wide as "n / n" from the start, so passing frame 10 or 100 does not
  // widen the counter and shove the scrubber sideways every loop
  count.style.minWidth = `${`${n} / ${n}`.length}ch`;
  let shown = null;
  return ({ frame, playing }) => {
    if (playing !== shown) {
      shown = playing;
      play.innerHTML = playing ? icons.pause : icons.play;
      const label = playing ? 'Pause (space)' : 'Play (space)';
      play.setAttribute('aria-label', label);
      play.title = label;
    }
    scrub.value = String(frame);
    scrub.setAttribute('aria-valuetext', `Frame ${frame + 1} of ${n}`);
    count.textContent = `${frame + 1} / ${n}`;
  };
}

/** Whether an IntersectionObserver callback's entries say "in view": the
 * LATEST entry. Scrolled away and straight back between two callbacks, the
 * batch is [left, entered], and the first entry would freeze a figure that is
 * on screen. */
export function intersecting(entries) {
  return entries[entries.length - 1].isIntersecting;
}

/** Where the image's inline width goes: `{ player, canvas }`, '' for none.
 * A percentage is of the column. On the canvas it would resolve against the
 * player, which shrinks to fit the canvas, so the figure came out a fraction
 * of its own size; the player takes it instead and the canvas fills the
 * player. Any other width is the canvas's own, as it was the image's. */
export function placeWidth(width) {
  if (width.endsWith('%')) return { player: width, canvas: '100%' };
  return { player: '', canvas: width };
}

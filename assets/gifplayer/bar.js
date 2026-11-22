/**
 * The control bar's decisions, kept out of index.js so `node --test` can
 * check them without a DOM: which action a key means, how the bar shows a
 * state, and what a batch of IntersectionObserver entries says.
 */

const KEYS = {
  ' ': 'toggle', k: 'toggle', K: 'toggle',
  ArrowLeft: 'back', PageUp: 'back',
  ArrowRight: 'next', PageDown: 'next', // presentation clickers send these
  Home: 'first', End: 'last',
  f: 'full', F: 'full',
};

// keys a focused control already answers natively
const NATIVE = {
  BUTTON: new Set([' ', 'Enter']),
  INPUT: new Set(['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End', 'PageUp', 'PageDown']),
};

/** The player action a keydown means, or null to leave it to the browser. */
export function keyAction(e) {
  if (e.altKey || e.ctrlKey || e.metaKey) return null;
  const name = KEYS[e.key];
  if (!name) return null;
  const native = NATIVE[e.target && e.target.tagName];
  if (native && native.has(e.key)) return null;
  return name;
}

/** A function that shows a controller state on the bar's elements. */
export function barView({ play, scrub, count }, n, icons) {
  return ({ frame, playing }) => {
    play.innerHTML = playing ? icons.pause : icons.play;
    const label = playing ? 'Pause (space)' : 'Play (space)';
    play.setAttribute('aria-label', label);
    play.title = label;
    scrub.value = String(frame);
    scrub.setAttribute('aria-valuetext', `Frame ${frame + 1} of ${n}`);
    count.textContent = `${frame + 1} / ${n}`;
  };
}

/** Whether an IntersectionObserver callback's entries say "in view". */
export function intersecting([e]) {
  return e.isIntersecting;
}

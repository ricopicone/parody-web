/**
 * Read-along: the section, read aloud, over the PDF the student writes on.
 *
 * Boots only when the server has a track for this section. Absent one it
 * leaves the viewer exactly as it was — read-along is additive, and must never
 * become a precondition for annotating.
 */
import { BlankMarks, blanksOnPage, nextBlank } from './blanks.js';
import { Clock } from './clock.js';
import { Highlight } from './highlight.js';
import { Reveal } from './reveal.js';
import { isRendered, pageAt } from './pageview.js';
import { clozeAt, showable, skipTarget, wordAt } from './track.js';

async function boot() {
  const root = document.querySelector('[data-ink-root]');
  if (!root) return;

  const base = root.dataset.base || '';
  let track;
  try {
    const response = await fetch(`${base}readalong/`,
                                 { headers: { Accept: 'application/json' } });
    if (!response.ok) return;           // no track: leave the viewer alone
    track = await response.json();
  } catch (err) {
    return;
  }

  const clozes = showable(track.clozes);
  const regions = track.regions || [];
  // A preview track has timings but no audio. A clock stands in for the
  // element so everything downstream — the frame loop, the holds, the
  // controls — is identical whether or not a voice has been synthesised.
  const audio = track.audio_url
    ? new Audio(track.audio_url)
    : new Clock(track.duration_ms);
  if (track.audio_url) audio.preload = 'auto';

  const scroller = root.querySelector('[data-ink-pages]');
  const reveal = new Reveal();
  const layers = new Map();             // page index -> Highlight
  const marks = new Map();              // page index -> BlankMarks

  let current = -1;                     // blank the navigator is sitting on
  let holding = -1;                     // cloze index we are stopped at
  let announced = -1;
  let following = true;

  root.dataset.readalong = 'idle';

  // A button as well as a key: the reader is holding a stylus, not resting
  // their hands on a keyboard. Shown only while maths is actually being read.
  const skipButton = document.createElement('button');
  skipButton.type = 'button';
  skipButton.className = 'readalong-skip';
  skipButton.textContent = 'Skip the equation';
  skipButton.hidden = true;
  root.appendChild(skipButton);
  skipButton.addEventListener('click', () => skip());

  /**
   * Finding the blanks without playing anything.
   *
   * A ruled gap looks like every other rule on a typeset page, so scrolling to
   * hunt for them does not work. This says how many there are and steps
   * between them; the marks layer keeps them visible once you are there.
   */
  const nav = document.createElement('div');
  nav.className = 'readalong-bar';
  nav.innerHTML = '<button type="button" data-play class="readalong-play">'
    + '<span data-play-glyph>\u25b6</span> <span data-play-label>Read aloud</span>'
    + '</button>'
    + '<span class="readalong-blanknav" data-blanknav>'
    + '<button type="button" data-prev aria-label="Previous blank">\u2039</button>'
    + '<span data-count></span>'
    + '<button type="button" data-next aria-label="Next blank">\u203a</button>'
    + '</span>';
  root.appendChild(nav);
  const counter = nav.querySelector('[data-count]');
  const playButton = nav.querySelector('[data-play]');
  const playGlyph = nav.querySelector('[data-play-glyph]');
  const playLabel = nav.querySelector('[data-play-label]');
  nav.querySelector('[data-blanknav]').hidden = clozes.length === 0;

  /** Keep the control saying what pressing it will do. */
  function showPlayState() {
    const state = root.dataset.readalong;
    const running = state === 'playing';
    playGlyph.textContent = running ? '\u275a\u275a' : '\u25b6';
    playLabel.textContent = running ? 'Pause'
      : state === 'holding' ? 'Continue'
      : state === 'paused' ? 'Resume'
      : state === 'done' ? 'Read again'
      : 'Read aloud';
  }

  /** The one entry point: start, pause, or continue, whichever applies. */
  function toggle() {
    if (holding >= 0) resume();
    else if (root.dataset.readalong === 'playing') pause();
    else if (root.dataset.readalong === 'done') { restart(); }
    else play();
    showPlayState();
  }
  playButton.addEventListener('click', toggle);

  function showCount() {
    counter.textContent = current < 0
      ? `${clozes.length} blank${clozes.length === 1 ? '' : 's'}`
      : `blank ${current + 1} of ${clozes.length}`;
  }
  showCount();
  showPlayState();

  function goToBlank(direction) {
    const at = nextBlank(clozes, current, direction);
    if (at < 0) return;
    current = at;
    const cloze = clozes[at];
    const page = pageAt(root, cloze.page, track.pages);
    if (page && scroller) {
      const row = page.el.parentElement || page.el;
      scroller.scrollTo({
        top: row.offsetTop + cloze.y0 * page.scale - scroller.clientHeight / 3,
        behavior: 'smooth',
      });
    }
    // The page may not hold a canvas yet; update whatever is there now and let
    // the next render pick the rest up.
    syncMarks();
    showCount();
  }

  nav.querySelector('[data-prev]').addEventListener('click', () => goToBlank(-1));
  nav.querySelector('[data-next]').addEventListener('click', () => goToBlank(1));

  const isDark = () => root.dataset.dark === '1';

  function layerFor(index) {
    const page = pageAt(root, index, track.pages);
    if (!page || !isRendered(page)) {
      // The viewer keeps canvases for only about three pages, so the page the
      // audio has reached may be a bare placeholder. Drop the highlight rather
      // than draw a mark over blank paper.
      const stale = layers.get(index);
      if (stale) { stale.destroy(); layers.delete(index); }
      const staleMark = marks.get(index);
      if (staleMark) { staleMark.destroy(); marks.delete(index); }
      return null;
    }
    let layer = layers.get(index);
    if (!layer) {
      layer = new Highlight(page, { dark: isDark() });
      layers.set(index, layer);
    } else {
      layer.fit(page);                  // the page may have been zoomed
    }

    return layer;
  }

  /**
   * Keep a marker layer on every rendered page that has blanks.
   *
   * Deliberately NOT driven by the frame loop. The marks exist so a reader can
   * find the blanks BEFORE pressing play — and animation frames do not run
   * when nothing is playing, nor at all in a background tab.
   */
  function syncMarks() {
    const wanted = new Set(clozes.map((c) => c.page));
    marks.forEach((mark, index) => {
      if (!wanted.has(index)) { mark.destroy(); marks.delete(index); }
    });
    for (const index of wanted) {
      // Only the page's box is needed, not its canvas. A placeholder already
      // has the right size, so the markers appear the moment the page exists
      // rather than waiting for it to finish rasterising — which is the point,
      // since the reader is looking for the blanks before anything plays.
      const page = pageAt(root, index, track.pages);
      if (!page) {
        const stale = marks.get(index);
        if (stale) { stale.destroy(); marks.delete(index); }
        continue;
      }
      let mark = marks.get(index);
      if (!mark) {
        mark = new BlankMarks(page, { dark: isDark() });
        mark.setBoxes(blanksOnPage(clozes, index));
        marks.set(index, mark);
      } else {
        mark.fit(page);
      }
      const active = current >= 0 ? (clozes[current] || {}).token : -1;
      mark.setActive(active);
    }
  }

  function clearOthers(keep) {
    layers.forEach((layer, index) => {
      if (index !== keep) layer.clear();
    });
  }

  function follow(page, y0) {
    if (!following || !scroller) return;
    const row = page.el.parentElement || page.el;
    const target = row.offsetTop + y0 - scroller.clientHeight / 2;
    if (Math.abs(scroller.scrollTop - target) > scroller.clientHeight / 3) {
      scroller.scrollTo({ top: target, behavior: 'smooth' });
    }
  }

  function paint(ms) {
    const index = wordAt(track.words, ms);
    if (index < 0) return;
    const word = track.words[index];
    if (!Number.isFinite(word.page)) return;
    const layer = layerFor(word.page);
    if (!layer) return;
    layer.show([word.x0, word.y0, word.x1, word.y1]);
    clearOthers(word.page);
    follow(layer.page, word.y0 * layer.page.scale);
  }

  function hold(index) {
    const cloze = clozes[index];
    const page = pageAt(root, cloze.page, track.pages);
    audio.pause();
    holding = index;
    current = index;
    showCount();
    root.dataset.readalong = 'holding';
    showPlayState();
    if (page) reveal.show(cloze, page);
  }

  function resume() {
    if (holding < 0) return;
    holding = -1;
    root.dataset.readalong = 'playing';
    reveal.fade();
    audio.play();
    showPlayState();
  }

  /** One frame's worth of work at `ms`. Separated from the rAF loop so it can
   *  be driven directly — a hidden tab fires no animation frames at all. */
  function step(ms) {
    if (audio instanceof Clock && ms >= track.duration_ms) {
      audio.pause();
      audio.dispatch('ended');
    }
    paint(ms);
    skipButton.hidden = skipTarget(regions, ms) === null || holding >= 0;
    const due = clozeAt(clozes, ms);
    if (due >= 0 && due !== announced) {
      announced = due;
      hold(due);
    }
  }

  function frame() {
    if (!audio.paused) step(audio.currentTime * 1000);
    requestAnimationFrame(frame);
  }

  // Auto-scroll must not fight a reader who is scrolling or drawing. Any
  // manual scroll hands control back; starting playback takes it again.
  scroller?.addEventListener('scroll', () => { syncMarks(); },
                             { passive: true });
  // A timer rather than an animation frame: pages arrive asynchronously, and
  // nothing here should depend on playback having started.
  setInterval(syncMarks, 1000);
  syncMarks();

  scroller?.addEventListener('wheel', () => { following = false; },
                             { passive: true });
  scroller?.addEventListener('touchmove', () => { following = false; },
                             { passive: true });

  function play() {
    following = true;
    root.dataset.readalong = 'playing';
    audio.play();
    showPlayState();
  }

  function pause() {
    root.dataset.readalong = 'paused';
    audio.pause();
    showPlayState();
  }

  function restart() {
    audio.currentTime = 0;
    announced = -1;
    play();
  }

  /**
   * Skip the rest of the equation being read.
   *
   * SRE has to be verbose to be unambiguous — a modest integral becomes a long
   * sentence — so a reader who has taken the point needs a way past it without
   * losing their place in the prose.
   */
  function skip() {
    const target = skipTarget(regions, audio.currentTime * 1000);
    if (target === null) return false;
    audio.currentTime = target / 1000;
    // Anything already passed must not fire on the way through.
    announced = clozeAt(clozes, target);
    step(target);
    return true;
  }

  document.addEventListener('keydown', (event) => {
    if (event.key === 'ArrowRight' && holding < 0) {
      if (skip()) event.preventDefault();
      return;
    }
    if (event.key !== ' ') return;
    // Space is the whole transport: start, pause, continue. It used to pause
    // and continue but never START, so a reader who had not opened the console
    // had no way in at all.
    if (event.target && /^(INPUT|TEXTAREA)$/.test(event.target.tagName)) return;
    event.preventDefault();
    toggle();
  });

  // Tapping the revealed answer continues, for a reader holding a stylus
  // rather than a keyboard.
  reveal.el.addEventListener('pointerdown', (event) => {
    event.preventDefault();
    resume();
  });

  audio.addEventListener('ended', () => {
    root.dataset.readalong = 'done';
    layers.forEach((layer) => layer.clear());
    showPlayState();
  });

  // Animation frames stop entirely while a tab is in the background, but audio
  // keeps playing — so the mark would freeze mid-sentence and then jump when
  // the reader came back. Repaint on return, at wherever the voice has got to.
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && !audio.paused) {
      step(audio.currentTime * 1000);
    }
  });

  window.parodyReadAlong = {
    audio, track, play, pause, resume, restart, toggle, step, skip, goToBlank,
    follow: (on) => { following = on; },
  };

  requestAnimationFrame(frame);
  document.dispatchEvent(new CustomEvent('readalong:ready',
                                         { detail: window.parodyReadAlong }));
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot);
} else {
  boot();
}

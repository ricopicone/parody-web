/**
 * Read-along: the section, read aloud, over the PDF the student writes on.
 *
 * Boots only when the server has a track for this section. Absent one it
 * leaves the viewer exactly as it was — read-along is additive, and must never
 * become a precondition for annotating.
 */
import { BlankMarks, blanksOnPage } from './blanks.js';
import { Clock } from './clock.js';
import { Highlight } from './highlight.js';
import { Reveal } from './reveal.js';
import { isRendered, pageAt } from './pageview.js';
import { clozeAt, revealAt, showable, skipTarget, wordAt } from './track.js';

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

  let current = -1;                     // blank most recently revealed
  let shown = -1;                       // blank whose plate is up
  let holding = -1;                     // cloze index we are stopped at
  let announced = -1;
  let following = true;

  root.dataset.readalong = 'idle';

  // A button as well as a key: the reader is holding a stylus, not resting
  // their hands on a keyboard. Shown only while maths is actually being read.
  const skipButton = document.createElement('button');
  skipButton.type = 'button';
  skipButton.className = 'readalong-skip';
  skipButton.textContent = 'Skip ahead';
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
    + '<button type="button" data-here class="readalong-here">Read from\u2026</button>'
    + '<button type="button" data-restart class="readalong-restart" '
    + 'aria-label="Start over" title="Start over">\u21ba</button>';
  root.appendChild(nav);
  const playButton = nav.querySelector('[data-play]');
  const playGlyph = nav.querySelector('[data-play-glyph]');
  const playLabel = nav.querySelector('[data-play-label]');

  const clock = (seconds) => {
    const total = Math.max(0, Math.floor(seconds));
    return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
  };

  /** Keep the control saying what pressing it will do. */
  function showPlayState() {
    const state = root.dataset.readalong;
    const running = state === 'playing';
    playGlyph.textContent = running ? '\u275a\u275a' : '\u25b6';
    playLabel.textContent = running ? 'Pause'
      : state === 'holding' ? 'Continue'
      : state === 'paused' ? 'Resume'
      : state === 'done' ? 'Read again'
      : root.dataset.readalongResume ? `Resume at ${clock(audio.currentTime)}`
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

  showPlayState();

  nav.querySelector('[data-restart]').addEventListener('click', () => restart());

  /**
   * "Read from here".
   *
   * The pen owns the page — a plain click draws on it — so this is an armed
   * mode rather than a bare click handler. Press the button, then tap a word;
   * the tap is taken in the capture phase so it never reaches the ink layer,
   * and the mode disarms itself immediately afterwards.
   */
  const hereButton = nav.querySelector('[data-here]');
  let arming = false;

  // Armed state has to be unmistakable: it is a two-step gesture (press, then
  // tap) on a page where a bare tap normally draws, and a reader who does not
  // notice the first step just taps, draws a dot, and concludes it is broken.
  const armBanner = document.createElement('div');
  armBanner.className = 'readalong-arm-banner';
  armBanner.textContent = 'Tap anywhere in the text to read from there — Esc to cancel';
  armBanner.hidden = true;
  root.appendChild(armBanner);

  function setArmed(on) {
    arming = on;
    armBanner.textContent =
      'Tap anywhere in the text to read from there \u2014 Esc to cancel';
    hereButton.textContent = on ? 'Tap a word\u2026' : 'Read from\u2026';
    armBanner.hidden = !on;
    if (on) root.dataset.readalongArming = '1';
    else delete root.dataset.readalongArming;
  }
  hereButton.addEventListener('click', () => setArmed(!arming));

  /** Seek to the word nearest a point on a page, in PDF points. */
  function readFrom(pageIndex, xPt, yPt) {
    let best = -1;
    let bestScore = Infinity;
    for (let i = 0; i < track.words.length; i += 1) {
      const w = track.words[i];
      if (w.page !== pageIndex || !Number.isFinite(w.x0)) continue;
      // Same line first, then horizontal distance: reading order, not
      // euclidean distance, is what a reader means by "from here".
      const dy = yPt < w.y0 ? w.y0 - yPt : yPt > w.y1 ? yPt - w.y1 : 0;
      const dx = xPt < w.x0 ? w.x0 - xPt : xPt > w.x1 ? xPt - w.x1 : 0;
      const score = dy * 1000 + dx;
      if (score < bestScore) { bestScore = score; best = i; }
    }
    if (best < 0) return false;
    const at = track.words[best].start_ms;
    audio.currentTime = at / 1000;
    announced = clozeAt(clozes, at);
    shown = -1;
    reveal.fade();
    play();
    return true;
  }

  /**
   * Take the tap, whatever kind of tap it is.
   *
   * THREE event types, all in the capture phase, because one is not enough:
   * the ink layer owns the page with `touch-action: none` and pointer capture,
   * a stylus and a mouse do not produce the same sequence, and some pointers
   * never surface a `pointerdown` here at all — which is why listening only
   * for that did nothing on a real click while working perfectly on a
   * synthesised one.
   *
   * `handled` collapses the duplicates: down and click for the same gesture
   * arrive within a few milliseconds and must seek once.
   */
  let handled = 0;

  function takeTap(event) {
    if (!arming) return;
    const now = Date.now();
    if (now - handled < 400) return;          // same gesture, second event
    const pageEl = event.target && event.target.closest
      && event.target.closest('.ink-page');
    if (!pageEl) return;
    handled = now;
    event.preventDefault();
    event.stopPropagation();

    const index = Number(pageEl.dataset.page) - 1;
    const page = pageAt(root, index, track.pages);
    let ok = false;
    if (page) {
      const box = pageEl.getBoundingClientRect();
      ok = readFrom(index, (event.clientX - box.left) / page.scale,
                    (event.clientY - box.top) / page.scale);
    }
    // Say what happened, either way. A silent miss is what made this look
    // like it "always starts at the beginning": the tap did nothing, and
    // pressing play afterwards started from the top.
    if (ok) {
      armBanner.textContent = `Reading from ${clock(audio.currentTime)}`;
      setTimeout(() => setArmed(false), 900);
    } else {
      armBanner.textContent = page
        ? 'No words there \u2014 tap on some text'
        : 'That page is not ready yet \u2014 scroll to it and try again';
    }
  }

  for (const type of ['pointerdown', 'mousedown', 'click']) {
    root.addEventListener(type, takeTap, true);   // capture: before the ink
  }

  // Leaves a trail when it goes wrong, so a report can say WHICH part missed
  // rather than only "it starts at the beginning".
  window.parodyReadAlongDebug = () => ({
    armed: arming,
    pagesInDom: [...root.querySelectorAll('.ink-page')].map(
      (el) => el.dataset.page),
    pageSizes: track.pages,
    wordsWithBoxes: track.words.filter((w) => Number.isFinite(w.x0)).length,
    currentTime: audio.currentTime,
  });

  /**
   * Where the reader got to last time.
   *
   * Kept per version of the section, so a re-imported or re-cut PDF does not
   * drop them somewhere that no longer corresponds. localStorage rather than
   * the server: it is a convenience, not part of the artifact, and it must not
   * cost a write on every pause.
   */
  const RESUME_KEY = `parody-readalong:${track.slice_key}:${track.voice_id}`;

  function rememberPosition() {
    try {
      const at = audio.currentTime;
      if (at > 5 && at < (track.duration_ms / 1000) - 5) {
        localStorage.setItem(RESUME_KEY, String(Math.floor(at)));
      } else {
        localStorage.removeItem(RESUME_KEY);
      }
    } catch (err) { /* private mode */ }
  }

  function savedPosition() {
    try {
      const raw = localStorage.getItem(RESUME_KEY);
      const at = raw ? parseInt(raw, 10) : 0;
      return Number.isFinite(at) && at > 0 ? at : 0;
    } catch (err) { return 0; }
  }

  const resumeAt = savedPosition();
  if (resumeAt) {
    audio.currentTime = resumeAt;
    announced = clozeAt(clozes, resumeAt * 1000);
    root.dataset.readalongResume = '1';
  }
  window.addEventListener('pagehide', rememberPosition);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') rememberPosition();
  });

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
    root.dataset.readalong = 'holding';
    showPlayState();
    if (page) reveal.show(cloze, page);   // already up; re-place after any scroll
  }

  function resume() {
    if (holding < 0) return;
    holding = -1;
    shown = -1;
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
    // Offered always, not only over maths: wanting to move on is not
    // something that only happens during an equation.
    skipButton.hidden = holding >= 0
      || skipTarget(regions, ms, track.words) === null;

    // The answer appears WHILE it is read, not after. Hearing a term and only
    // then seeing it made the two feel unconnected.
    const speaking = revealAt(clozes, ms);
    if (speaking >= 0 && speaking !== shown) {
      shown = speaking;
      current = speaking;
      const cloze = clozes[speaking];
      const page = pageAt(root, cloze.page, track.pages);
      if (page) reveal.show(cloze, page);
      syncMarks();
    }

    // The pause still waits for the whole term to be said.
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
    delete root.dataset.readalongResume;
    root.dataset.readalong = 'playing';
    audio.play();
    showPlayState();
  }

  function pause() {
    root.dataset.readalong = 'paused';
    audio.pause();
    showPlayState();
    rememberPosition();
  }

  function restart() {
    delete root.dataset.readalongResume;
    try { localStorage.removeItem(RESUME_KEY); } catch (err) { /* ignore */ }
    audio.currentTime = 0;
    announced = -1;
    shown = -1;
    reveal.fade();
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
    const target = skipTarget(regions, audio.currentTime * 1000, track.words);
    if (target === null) return false;
    audio.currentTime = target / 1000;
    // Anything already passed must not fire on the way through.
    announced = clozeAt(clozes, target);
    step(target);
    return true;
  }

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && arming) {
      setArmed(false);
      return;
    }
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
    audio, track, play, pause, resume, restart, toggle, step, skip, readFrom,
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

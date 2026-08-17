/**
 * Read-along: the section, read aloud, over the PDF the student writes on.
 *
 * Boots only when the server has a track for this section. Absent one it
 * leaves the viewer exactly as it was — read-along is additive, and must never
 * become a precondition for annotating.
 */
import { Clock } from './clock.js';
import { Highlight } from './highlight.js';
import { Reveal } from './reveal.js';
import { isRendered, pageAt } from './pageview.js';
import { clozeAt, showable, wordAt } from './track.js';

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

  let holding = -1;                     // cloze index we are stopped at
  let announced = -1;
  let following = true;

  root.dataset.readalong = 'idle';

  const isDark = () => root.dataset.dark === '1';

  function layerFor(index) {
    const page = pageAt(root, index, track.pages);
    if (!page || !isRendered(page)) {
      // The viewer keeps canvases for only about three pages, so the page the
      // audio has reached may be a bare placeholder. Drop the highlight rather
      // than draw a mark over blank paper.
      const stale = layers.get(index);
      if (stale) { stale.destroy(); layers.delete(index); }
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
    root.dataset.readalong = 'holding';
    if (page) reveal.show(cloze, page);
  }

  function resume() {
    if (holding < 0) return;
    holding = -1;
    root.dataset.readalong = 'playing';
    reveal.fade();
    audio.play();
  }

  /** One frame's worth of work at `ms`. Separated from the rAF loop so it can
   *  be driven directly — a hidden tab fires no animation frames at all. */
  function step(ms) {
    if (audio instanceof Clock && ms >= track.duration_ms) {
      audio.pause();
      audio.dispatch('ended');
    }
    paint(ms);
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
  scroller?.addEventListener('wheel', () => { following = false; },
                             { passive: true });
  scroller?.addEventListener('touchmove', () => { following = false; },
                             { passive: true });

  function play() {
    following = true;
    root.dataset.readalong = 'playing';
    audio.play();
  }

  function pause() {
    root.dataset.readalong = 'paused';
    audio.pause();
  }

  document.addEventListener('keydown', (event) => {
    if (event.key !== ' ') return;
    if (holding >= 0) {
      event.preventDefault();
      resume();
    } else if (root.dataset.readalong === 'playing') {
      event.preventDefault();
      pause();
    }
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
    audio, track, play, pause, resume, step,
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

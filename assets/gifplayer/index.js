/**
 * Play controls for animated figures.
 *
 * A browser cannot pause a GIF in an <img>, and the books' animations loop
 * forever. This finds every GIF figure on the page, draws it on a canvas
 * instead, and puts a bar under it: first frame, previous frame, play/pause,
 * next frame, a scrubber, "k / N", and full screen for lecturing.
 *
 * The <img> stays in the page, hidden. If anything here fails (an old
 * browser, a fetch error, a file this decoder does not understand) the image
 * is left exactly as it was: today's looping GIF.
 */
import { parseGif, Compositor } from './decode.js';
import { Controller } from './controller.js';
import { barView, intersecting, keyAction } from './bar.js';

const svg = (body) =>
  `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" `
  + `stroke="currentColor" stroke-width="1.6" stroke-linecap="round" `
  + `stroke-linejoin="round" aria-hidden="true" focusable="false">${body}</svg>`;

// Drawn on the 24-grid at 1.6 stroke, as the annotator's tools and _icon.html.
const ICONS = {
  first: svg('<path d="M6.5 6v12"/><path d="M18 6.5v11L9.5 12z"/>'),
  back: svg('<path d="M15 6.5v11L6.5 12z"/><path d="M18 6v12"/>'),
  next: svg('<path d="M9 6.5v11l8.5-5.5z"/><path d="M6 6v12"/>'),
  play: svg('<path d="M8 5.5v13L18.5 12z"/>'),
  pause: svg('<path d="M8.5 6v12"/><path d="M15.5 6v12"/>'),
  full: svg('<path d="M4.5 9V4.5H9"/><path d="M15 4.5h4.5V9"/><path d="M19.5 15v4.5H15"/><path d="M9 19.5H4.5V15"/>'),
  unfull: svg('<path d="M9 4.5V9H4.5"/><path d="M19.5 9H15V4.5"/><path d="M15 19.5V15h4.5"/><path d="M4.5 15H9v4.5"/>'),
};

function isGif(img) {
  try {
    return new URL(img.currentSrc || img.src, location.href).pathname.toLowerCase().endsWith('.gif');
  } catch {
    return false;
  }
}

function loaded(img) {
  if (img.complete && img.naturalWidth) return Promise.resolve();
  return new Promise((resolve, reject) => {
    img.addEventListener('load', () => resolve(), { once: true });
    img.addEventListener('error', () => reject(new Error('image failed to load')), { once: true });
  });
}

function button(cls, label, icon) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = cls;
  b.setAttribute('aria-label', label);
  b.title = label;
  b.innerHTML = icon;
  return b;
}

const fullscreenElement = () => document.fullscreenElement || document.webkitFullscreenElement;

async function enhance(img) {
  // after the <img> has loaded, so this is a cache hit, not a second download
  await loaded(img);
  const res = await fetch(img.currentSrc || img.src, { cache: 'force-cache', credentials: 'same-origin' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const gif = parseGif(new Uint8Array(await res.arrayBuffer()));
  const n = gif.frames.length;
  if (n < 2) return; // a still image needs no controls

  const compositor = new Compositor(gif);
  const alt = img.getAttribute('alt') || '';

  const player = document.createElement('div');
  player.className = 'gif-player';
  player.tabIndex = 0;
  player.setAttribute('role', 'group');
  player.setAttribute('aria-label', alt ? `Animation: ${alt}` : 'Animation');

  const canvas = document.createElement('canvas');
  canvas.width = gif.width;
  canvas.height = gif.height;
  // the image's alt, where it has one; the books' figures mostly leave alt
  // empty and are described by their figcaption, so then the canvas is
  // decoration a screen reader should skip, as it skipped the image
  if (alt) {
    canvas.setAttribute('role', 'img');
    canvas.setAttribute('aria-label', alt);
  } else {
    canvas.setAttribute('aria-hidden', 'true');
  }
  const style = img.getAttribute('style');
  if (style) canvas.setAttribute('style', style); // an author's width/height
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('no 2d canvas');
  // the compositor always returns the same array, so one ImageData serves
  const image = new ImageData(compositor.frame(0), gif.width, gif.height);
  const render = (i) => {
    compositor.frame(i);
    ctx.putImageData(image, 0, 0);
  };
  render(0);

  const bar = document.createElement('div');
  bar.className = 'gif-bar';
  const first = button('gif-first', 'First frame (Home)', ICONS.first);
  const back = button('gif-back', 'Previous frame (←)', ICONS.back);
  const play = button('gif-play', 'Play (space)', ICONS.play);
  const next = button('gif-next', 'Next frame (→)', ICONS.next);
  const scrub = document.createElement('input');
  scrub.type = 'range';
  scrub.className = 'gif-scrub';
  scrub.min = '0';
  scrub.max = String(n - 1);
  scrub.step = '1';
  scrub.value = '0';
  scrub.setAttribute('aria-label', 'Frame');
  const count = document.createElement('span');
  count.className = 'gif-count';
  count.setAttribute('aria-hidden', 'true');
  const full = button('gif-full', 'Full screen (F)', ICONS.full);
  const canFull = (player.requestFullscreen || player.webkitRequestFullscreen)
    && (document.fullscreenEnabled || document.webkitFullscreenEnabled);
  if (!canFull) full.hidden = true;
  bar.append(first, back, play, next, scrub, count, full);
  player.append(canvas, bar);

  const show = barView({ play, scrub, count }, n, ICONS);

  const ctl = new Controller({
    count: n,
    delays: gif.frames.map((f) => f.delay),
    loop: gif.loop,
    render,
    schedule: (fn, ms) => setTimeout(fn, ms),
    cancel: (h) => clearTimeout(h),
    onChange: show,
  });

  const toggleFull = () => {
    if (fullscreenElement() === player) {
      (document.exitFullscreen || document.webkitExitFullscreen).call(document);
    } else {
      const req = player.requestFullscreen || player.webkitRequestFullscreen;
      const p = req.call(player);
      if (p && p.catch) p.catch(() => {});
    }
  };
  const onFullChange = () => {
    const on = fullscreenElement() === player;
    full.innerHTML = on ? ICONS.unfull : ICONS.full;
    const label = on ? 'Exit full screen (F)' : 'Full screen (F)';
    full.setAttribute('aria-label', label);
    full.title = label;
  };
  document.addEventListener('fullscreenchange', onFullChange);
  document.addEventListener('webkitfullscreenchange', onFullChange);

  const act = {
    toggle: () => ctl.toggle(),
    back: () => ctl.step(-1),
    next: () => ctl.step(+1),
    first: () => ctl.first(),
    last: () => ctl.last(),
    full: () => { if (canFull) toggleFull(); },
  };
  first.addEventListener('click', act.first);
  back.addEventListener('click', act.back);
  play.addEventListener('click', act.toggle);
  next.addEventListener('click', act.next);
  full.addEventListener('click', act.full);
  scrub.addEventListener('input', () => ctl.seek(scrub.value));
  canvas.addEventListener('click', () => {
    ctl.toggle();
    player.focus({ preventScroll: true });
  });
  // on the player, never the window: two figures on a page, or a reader
  // typing elsewhere, must not have their keys taken
  player.addEventListener('keydown', (e) => {
    const name = keyAction(e);
    if (!name) return;
    e.preventDefault();
    act[name]();
  });

  // a caption-less figure keeps its id on the <img>; cross-refs land on it
  if (img.id) {
    player.id = img.id;
    img.removeAttribute('id');
  }
  img.before(player);
  img.hidden = true;

  // stop while out of view, and free the snapshots once well away from it
  if ('IntersectionObserver' in window) {
    new IntersectionObserver((es) => ctl.setVisible(intersecting(es))).observe(player);
    new IntersectionObserver((es) => { if (!intersecting(es)) compositor.dropCache(); },
      { rootMargin: '200% 0px' }).observe(player);
  }

  const still = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (still) ctl.seek(0);
  else ctl.play();
}

function init() {
  for (const img of document.querySelectorAll('img.figure-img')) {
    if (!isGif(img)) continue;
    enhance(img).catch((err) => console.warn('[gifplayer] left as an image:', img.src, err));
  }
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
else init();

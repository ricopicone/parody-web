/**
 * The annotating PDF viewer.
 *
 * Replaces parody-web's default stage (an iframe around the browser's PDF
 * plugin) with pdf.js canvases we can draw on. Boots only when the reader may
 * annotate; otherwise it leaves the page alone and the server's fallback
 * stands.
 */
import { PageView, PAD_RATIO, ZOOM_STEPS } from './pages.js';
import { pinchDistance, pinchMidpoint, stepFor, anchoredScroll } from './pinch.js';
import { InkLayer } from './ink.js';
import { InkStore, PAD } from './store.js';
import { LayerSet } from './layers.js';
import { InkApi } from './api.js';
import { Saver, OK, FAILED } from './saving.js';
import { PointerGate } from './pointer-gate.js';
import { isDark, themeColors } from './theme.js';
import { bindPrint } from './print.js';
import { Tools } from './tools.js';
import { bindKeys, buildToolbar } from './toolbar.js';

const SAVE_DEBOUNCE_MS = 500;
const FINGER_DRAWS_KEY = 'parody-ink-finger-draws';

/** Off unless this browser has been told otherwise: the stylus is the default. */
function savedFingerDraws() {
  try {
    return localStorage.getItem(FINGER_DRAWS_KEY) === '1';
  } catch (err) {
    return false;                                          // private mode
  }
}

async function boot() {
  const root = document.querySelector('[data-ink-root]');
  if (!root) return;

  const { base, pdfUrl, sliceKey, bookSha, pages } = root.dataset;
  const api = new InkApi(base);
  const loaded = await api.load(sliceKey);
  if (!loaded) return;                    // not signed in, or nothing to draw on

  let saveTimer = null;
  const store = new InkStore(loaded.strokes, {
    pads: loaded.pads || {},
    onChange: () => {
      root.dataset.dirty = '1';
      // A margin that has just gained its first mark should stop looking empty.
      layers.forEach((pair, number) => {
        pair.pad.host.dataset.used = store.padUsed(number) ? '1' : '0';
      });
      clearTimeout(saveTimer);
      saveTimer = setTimeout(save, SAVE_DEBOUNCE_MS);
    },
  });

  const payload = () => ({
    sliceKey: loaded.slice_key || sliceKey,
    bookSha,
    pages: pages ? JSON.parse(pages) : null,
    strokes: store.toJSON(),
    pads: store.padsToJSON(),
  });

  // A save that does not land has to be visible. It used to set `dirty` and
  // say nothing, so a reader whose section had outgrown the request-body
  // ceiling went on annotating while every stroke was thrown away (task #667).
  const notice = document.createElement('span');
  notice.className = 'ink-save-state';
  notice.setAttribute('role', 'status');
  notice.hidden = true;
  root.querySelector('[data-ink-toolbar]')?.after(notice);

  const saver = new Saver(api, {
    onState(state) {
      root.dataset.saveState = state;
      if (state === OK) delete root.dataset.dirty;
      notice.hidden = state !== FAILED;
      if (state === FAILED) {
        notice.textContent = 'Not saved — still trying. Keep this tab open.';
      }
    },
  });

  const save = () => saver.save(payload);

  // The last line of defence: if ink is still unsaved as the page goes away,
  // the reader is warned rather than finding out later that it never landed.
  window.addEventListener('beforeunload', (event) => {
    if (!saver.pending) return;
    event.preventDefault();
    event.returnValue = '';
  });
  window.addEventListener('pagehide', () => {
    if (saver.pending || root.dataset.dirty) api.saveOnExit(payload());
  });

  const tools = new Tools();
  const gate = new PointerGate({ fingerDraws: savedFingerDraws() });

  // Two ink layers per page — the page and its margin — built when the page
  // renders and given up when it scrolls out of the window, which is the same
  // window pdf.js's own canvases live in. Holding them all instead cost 150 MB
  // on a six-page section at dpr 2 and never gave any of it back (task #675).
  const layers = new LayerSet((entry) => ({
    page: new InkLayer(entry, { store, tools, gate, theme: current }),
    pad: new InkLayer(entry, { store, tools, gate, theme: current,
                               surface: PAD, host: entry.pad,
                               width: entry.viewport.width * PAD_RATIO }),
  }));

  // The paper follows the reader's theme. The page itself is inverted by a
  // CSS filter on its canvas (see annotate.css) rather than re-rendered, so a
  // theme change costs nothing and survives any zoom.
  const theme = () => {
    const dark = isDark();
    const { paper, ink } = themeColors();
    return { dark, paper, ink };
  };
  let current = theme();
  root.dataset.dark = current.dark ? '1' : '0';

  const view = new PageView(root.querySelector('[data-ink-pages]'), {
    onPageReady: (entry) => {
      const { pair, built } = layers.ensure(entry);
      // A page is announced ready only after it has been released, so this
      // almost always builds fresh at the current scale. Belt and braces for
      // the case where it did not: layers the reader may be mid-stroke on are
      // moved to the new scale rather than thrown away.
      if (!built) {
        pair.page.resize(entry.viewport);
        pair.pad.resize(entry.viewport, entry.viewport.width * PAD_RATIO);
      }
      entry.pad.dataset.used = store.padUsed(entry.number) ? '1' : '0';
    },
    // Scrolling past a page returns its stages. The strokes are safe: they
    // live in the store, and a page scrolled back to rebuilds every path from
    // it — the layer never held anything the store does not.
    onPageGone: (entry) => layers.release(entry.number),
  });

  function applyTheme() {
    current = theme();
    // The page inverts through CSS; only the reader's own ink needs redrawing,
    // because its colour rule is applied when the strokes are painted.
    root.dataset.dark = current.dark ? '1' : '0';
    eachLayer((l) => l.setTheme(current));
  }

  const eachLayer = (fn) => layers.forEach((pair) => { fn(pair.page); fn(pair.pad); });
  const redrawAll = () => eachLayer((l) => l.redraw());
  let chrome = null;
  const actions = {
    undo: () => { store.undo(); redrawAll(); },
    redo: () => { store.redo(); redrawAll(); },
    zoomIn: () => chrome?.showZoom(view.stepZoom(+1) * 100),
    zoomOut: () => chrome?.showZoom(view.stepZoom(-1) * 100),
    zoomReset: () => chrome?.showZoom(view.setZoom(1) * 100),
    print: null,          // filled in below, once the root is known
    // A tablet with no stylus: the reader trades scrolling and pinch-zoom for
    // being able to draw with a finger, and gets both back by turning it off.
    fingerDraws: () => gate.fingerDraws,
    toggleFingerDraws: () => {
      gate.fingerDraws = !gate.fingerDraws;
      try {
        localStorage.setItem(FINGER_DRAWS_KEY, gate.fingerDraws ? '1' : '0');
      } catch (err) { /* private mode */ }
      // The pages already built keep the touch-action they were bound with.
      eachLayer((l) => l.applyTouchAction());
      return gate.fingerDraws;
    },
    toggleTheme: () => {
      const next = isDark() ? 'light' : 'dark';
      document.documentElement.dataset.theme = next;
      try { localStorage.setItem('parody-theme', next); } catch (err) { /* private mode */ }
      applyTheme();
    },
  };

  // ⌘P prints the composited PDF rather than the DOM: the DOM has canvases
  // only for the pages near the viewport, and in dark mode they carry an
  // inversion filter a browser would happily print.
  actions.print = bindPrint(root);

  // The File > Print menu cannot be intercepted, so the print stylesheet has
  // to cope. It turns the page's dark-mode inversion off — but the ink is
  // *drawn* light in dark mode, which on white paper is invisible. Repaint it
  // in the colours the reader actually chose for the duration of the print.
  window.addEventListener('beforeprint', () => {
    if (current.dark) eachLayer((l) => l.setTheme({ ...current, dark: false }));
  });
  window.addEventListener('afterprint', () => {
    if (current.dark) eachLayer((l) => l.setTheme(current));
  });

  const toolbar = document.querySelector('[data-ink-toolbar]');
  if (toolbar) chrome = buildToolbar(toolbar, tools, actions);
  bindKeys(tools, actions);
  chrome?.showZoom(100);

  const scroller = root.querySelector('[data-ink-pages]');
  let ticking = false;
  scroller.addEventListener('scroll', () => {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(() => { view.update(); ticking = false; });
  }, { passive: true });

  // Pinch zooms the VIEWER, not the browser.
  //
  // The browser's own pinch magnifies the whole application: the reader zooms
  // in on a figure and the toolbar leaves with everything else. Reserved for
  // us by the gate's touch-action ('pan-x pan-y' keeps one-finger scrolling
  // native and holds back the rest) and mapped onto the same ZOOM_STEPS
  // ladder the + and − buttons climb, so the readout follows too.
  let pinch = null;

  scroller.addEventListener('touchstart', (event) => {
    if (event.touches.length !== 2) return;
    // Two fingers are a gesture, never a stroke — this matters only with
    // finger drawing on, where the first finger did start one.
    eachLayer((l) => l.abandon());
    const box = scroller.getBoundingClientRect();
    const mid = pinchMidpoint(event.touches);
    pinch = {
      from: pinchDistance(event.touches),
      zoom: view.zoom,
      focal: { x: mid.x - box.left, y: mid.y - box.top },
    };
    if (event.cancelable) event.preventDefault();
  }, { passive: false });

  scroller.addEventListener('touchmove', (event) => {
    if (!pinch || event.touches.length !== 2) return;
    if (event.cancelable) event.preventDefault();
    const next = stepFor(pinch.zoom,
                         pinchDistance(event.touches) / pinch.from, ZOOM_STEPS);
    if (next === view.zoom) return;
    // setZoom re-anchors on the scrollbar's position, which is not where the
    // fingers are; take the scroll back afterwards so the figure being
    // pinched stays under them.
    const before = { zoom: view.zoom, top: scroller.scrollTop,
                     left: scroller.scrollLeft };
    chrome?.showZoom(view.setZoom(next) * 100);
    scroller.scrollTop =
      anchoredScroll(before.top, pinch.focal.y, before.zoom, view.zoom);
    scroller.scrollLeft =
      anchoredScroll(before.left, pinch.focal.x, before.zoom, view.zoom);
  }, { passive: false });

  // Lifting either finger ends it; the next pinch measures itself afresh.
  const endPinch = (event) => { if (event.touches.length < 2) pinch = null; };
  scroller.addEventListener('touchend', endPinch);
  scroller.addEventListener('touchcancel', endPinch);

  wireCarryForward(root, api);
  wireVersionSwitch();

  // Following the OS, or another tab of the same book, without being asked.
  if (window.matchMedia) {
    window.matchMedia('(prefers-color-scheme: dark)')
      .addEventListener('change', () => {
        if (!document.documentElement.dataset.theme) applyTheme();
      });
  }
  window.addEventListener('storage', (event) => {
    if (event.key !== 'parody-theme') return;
    if (event.newValue === 'dark' || event.newValue === 'light') {
      document.documentElement.dataset.theme = event.newValue;
      applyTheme();
    }
  });

  // pdf.js continues rendering on animation frames, which do not fire while
  // the tab is in the background — a page opened in a background tab can sit
  // unfinished until the reader comes to it. Nudge when they do.
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') view.update();
  });

  await view.open(pdfUrl);
  root.dataset.ready = '1';
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot);
} else {
  boot();
}


/**
 * The offer to bring earlier notes onto this version.
 *
 * Offered, never automatic: usually only the page number changed, but when the
 * section really changed, moving ink silently would put it in the wrong place.
 */
function wireCarryForward(root, api) {
  const prompt = root.querySelector('[data-ink-carry]');
  if (!prompt) return;
  prompt.querySelector('[data-ink-carry-no]')
    ?.addEventListener('click', () => prompt.remove());
  prompt.querySelector('[data-ink-carry-yes]')
    ?.addEventListener('click', async (event) => {
      const { from, to } = event.currentTarget.dataset;
      const { ok, status } = await api.carryForward(from, to);
      if (ok) {
        window.location.reload();
        return;
      }
      prompt.textContent = status === 409
        ? 'This version already has notes on it.'
        : 'Could not bring the notes forward.';
    });
}

/** Switching to another version reloads onto it; each version is its own PDF. */
function wireVersionSwitch() {
  const select = document.querySelector('[data-ink-versions]');
  if (!select) return;
  select.addEventListener('change', () => {
    const url = new URL(window.location.href);
    url.searchParams.set('v', select.value);
    window.location.assign(url);
  });
}

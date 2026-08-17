/**
 * The annotating PDF viewer.
 *
 * Replaces parody-web's default stage (an iframe around the browser's PDF
 * plugin) with pdf.js canvases we can draw on. Boots only when the reader may
 * annotate; otherwise it leaves the page alone and the server's fallback
 * stands.
 */
import { PageView } from './pages.js';
import { InkLayer } from './ink.js';
import { InkStore } from './store.js';
import { InkApi } from './api.js';
import { PointerGate } from './pointer-gate.js';
import { isDark, themeColors } from './theme.js';
import { bindPrint } from './print.js';
import { Tools } from './tools.js';
import { bindKeys, buildToolbar } from './toolbar.js';

const SAVE_DEBOUNCE_MS = 500;

async function boot() {
  const root = document.querySelector('[data-ink-root]');
  if (!root) return;

  const { base, pdfUrl, sliceKey, bookSha, pages } = root.dataset;
  const api = new InkApi(base);
  const loaded = await api.load(sliceKey);
  if (!loaded) return;                    // not signed in, or nothing to draw on

  let saveTimer = null;
  const store = new InkStore(loaded.strokes, {
    onChange: () => {
      root.dataset.dirty = '1';
      clearTimeout(saveTimer);
      saveTimer = setTimeout(save, SAVE_DEBOUNCE_MS);
    },
  });

  const payload = () => ({
    sliceKey: loaded.slice_key || sliceKey,
    bookSha,
    pages: pages ? JSON.parse(pages) : null,
    strokes: store.toJSON(),
  });

  async function save() {
    if (await api.save(payload())) delete root.dataset.dirty;
  }
  window.addEventListener('pagehide', () => {
    if (root.dataset.dirty) api.saveOnExit(payload());
  });

  const tools = new Tools();
  const gate = new PointerGate();
  const layers = new Map();

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
      const existing = layers.get(entry.number);
      // After a zoom the layer is still there but drawn at the old scale.
      if (existing) existing.resize(entry.viewport);
      else layers.set(entry.number,
                      new InkLayer(entry, { store, tools, gate, theme: current }));
    },
  });

  function applyTheme() {
    current = theme();
    // The page inverts through CSS; only the reader's own ink needs redrawing,
    // because its colour rule is applied when the strokes are painted.
    root.dataset.dark = current.dark ? '1' : '0';
    layers.forEach((layer) => layer.setTheme(current));
  }

  const redrawAll = () => layers.forEach((layer) => layer.redraw());
  let chrome = null;
  const actions = {
    undo: () => { store.undo(); redrawAll(); },
    redo: () => { store.redo(); redrawAll(); },
    zoomIn: () => chrome?.showZoom(view.stepZoom(+1) * 100),
    zoomOut: () => chrome?.showZoom(view.stepZoom(-1) * 100),
    zoomReset: () => chrome?.showZoom(view.setZoom(1) * 100),
    print: null,          // filled in below, once the root is known
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
    if (current.dark) layers.forEach((l) => l.setTheme({ ...current, dark: false }));
  });
  window.addEventListener('afterprint', () => {
    if (current.dark) layers.forEach((l) => l.setTheme(current));
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

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
import { Tools, bindKeys, buildToolbar } from './toolbar.js';

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

  const view = new PageView(root.querySelector('[data-ink-pages]'), {
    onPageReady: (entry) => {
      if (!layers.has(entry.number)) {
        layers.set(entry.number, new InkLayer(entry, { store, tools, gate }));
      }
    },
  });

  const redrawAll = () => layers.forEach((layer) => layer.redraw());
  const toolbar = document.querySelector('[data-ink-toolbar]');
  if (toolbar) {
    buildToolbar(toolbar, tools, {
      undo: () => { store.undo(); redrawAll(); },
      redo: () => { store.redo(); redrawAll(); },
    });
  }
  bindKeys(tools, {
    undo: () => { store.undo(); redrawAll(); },
    redo: () => { store.redo(); redrawAll(); },
  });

  const scroller = root.querySelector('[data-ink-pages]');
  let ticking = false;
  scroller.addEventListener('scroll', () => {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(() => { view.update(); ticking = false; });
  }, { passive: true });

  wireCarryForward(root, api);
  wireVersionSwitch();

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

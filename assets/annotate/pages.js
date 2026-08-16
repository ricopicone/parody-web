/**
 * Rendering the PDF, a window of pages at a time.
 *
 * Every page gets a placeholder of the right size immediately, so the document
 * has its true length and the scrollbar does not jump as pages arrive. Only
 * pages near the viewport hold a rendered canvas; the rest release theirs.
 * A 100-page section otherwise exhausts memory on an iPad, which is also why
 * the full-book PDF is not annotatable at all.
 */
import * as pdfjsLib from 'pdfjs-dist';
import { pageAt, windowAround } from './paged.js';

// The worker cannot be inlined into the bundle, so the template hands us its
// hashed static URL on the script tag that loaded us.
pdfjsLib.GlobalWorkerOptions.workerSrc =
  document.querySelector('script[data-pdf-worker]')?.dataset.pdfWorker || '';

export const ZOOM_STEPS = [0.6, 0.75, 0.9, 1, 1.15, 1.35, 1.6, 2, 2.5, 3];

export class PageView {
  constructor(container, { scale = 1.25, onPageReady, onPageGone } = {}) {
    this.container = container;
    this.baseScale = scale;
    this.zoom = 1;
    this.onPageReady = onPageReady || (() => {});
    this.onPageGone = onPageGone || (() => {});
    this.entries = [];
    this.doc = null;
    this.dpr = window.devicePixelRatio || 1;
    this._watchDpr();
  }

  get scale() {
    return this.baseScale * this.zoom;
  }

  /**
   * Re-render when the device pixel ratio changes.
   *
   * Chrome's browser zoom raises devicePixelRatio, and a canvas rasterised at
   * the old ratio is simply stretched — which is why plain browser zoom made
   * the page look pixelated. Nothing else notices, so nothing else fixed it.
   */
  _watchDpr() {
    const current = window.devicePixelRatio || 1;
    const query = window.matchMedia(`(resolution: ${current}dppx)`);
    query.addEventListener('change', () => {
      this.dpr = window.devicePixelRatio || 1;
      this.rerender();
      this._watchDpr();          // re-arm for the new ratio
    }, { once: true });
  }

  /** Set the zoom level, keeping the reader roughly where they were. */
  setZoom(zoom) {
    const next = Math.min(Math.max(zoom, ZOOM_STEPS[0]),
                          ZOOM_STEPS[ZOOM_STEPS.length - 1]);
    if (next === this.zoom) return this.zoom;
    const anchor = this.container.scrollTop / (this.container.scrollHeight || 1);
    this.zoom = next;
    this._resize();
    this.container.scrollTop = anchor * this.container.scrollHeight;
    this.rerender();
    return this.zoom;
  }

  stepZoom(direction) {
    const at = ZOOM_STEPS.findIndex((z) => Math.abs(z - this.zoom) < 1e-6);
    const index = at === -1
      ? ZOOM_STEPS.findIndex((z) => z > this.zoom)
      : at + direction;
    return this.setZoom(ZOOM_STEPS[Math.min(Math.max(index, 0),
                                            ZOOM_STEPS.length - 1)]);
  }

  /** Resize placeholders to the new scale before anything re-renders. */
  _resize() {
    for (const entry of this.entries) {
      entry.viewport = entry.page.getViewport({ scale: this.scale });
      entry.el.style.width = `${entry.viewport.width}px`;
      entry.el.style.height = `${entry.viewport.height}px`;
    }
  }

  /** Drop every canvas and draw the visible window again at the current scale. */
  rerender() {
    for (const entry of this.entries) this._release(entry);
    this.update();
  }

  async open(url) {
    this.doc = await pdfjsLib.getDocument(url).promise;
    this.container.innerHTML = '';
    for (let number = 1; number <= this.doc.numPages; number += 1) {
      const page = await this.doc.getPage(number);
      const viewport = page.getViewport({ scale: this.scale });
      const el = document.createElement('div');
      el.className = 'ink-page';
      el.style.width = `${viewport.width}px`;
      el.style.height = `${viewport.height}px`;
      el.dataset.page = String(number);
      this.container.appendChild(el);
      this.entries.push({ number, page, viewport, el, canvas: null, layer: null });
    }
    this.update();
    return this.doc.numPages;
  }

  /** Which pages should hold a canvas right now. */
  update() {
    const tops = this.entries.map((e) => e.el.offsetTop);
    const middle = this.container.scrollTop + this.container.clientHeight / 2;
    const keep = new Set(windowAround(pageAt(middle, tops), this.entries.length, 1));
    this.entries.forEach((entry, index) => {
      if (keep.has(index)) this._render(entry);
      else this._release(entry);
    });
  }

  async _render(entry) {
    if (entry.canvas || entry.rendering) return;
    entry.rendering = true;
    const canvas = document.createElement('canvas');
    canvas.className = 'ink-page-canvas';
    const dpr = this.dpr;
    canvas.width = Math.floor(entry.viewport.width * dpr);
    canvas.height = Math.floor(entry.viewport.height * dpr);
    canvas.style.width = `${entry.viewport.width}px`;
    canvas.style.height = `${entry.viewport.height}px`;
    const context = canvas.getContext('2d');
    context.scale(dpr, dpr);
    entry.el.prepend(canvas);
    entry.canvas = canvas;
    await entry.page.render({ canvasContext: context,
                              viewport: entry.viewport }).promise;
    entry.rendering = false;
    this.onPageReady(entry);
  }

  _release(entry) {
    if (!entry.canvas) return;
    entry.canvas.remove();          // the ink layer is handled separately
    entry.canvas = null;
    this.onPageGone(entry);
  }
}

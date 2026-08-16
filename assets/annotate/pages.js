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

export class PageView {
  constructor(container, { scale = 1.4, onPageReady } = {}) {
    this.container = container;
    this.scale = scale;
    this.onPageReady = onPageReady || (() => {});
    this.entries = [];
    this.doc = null;
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
    const dpr = window.devicePixelRatio || 1;
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
    entry.canvas.remove();          // the ink layer stays; only the PDF goes
    entry.canvas = null;
  }
}

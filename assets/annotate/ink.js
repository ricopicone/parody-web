/**
 * The drawing layer for one page.
 *
 * One Konva stage per page, sized to the rendered page and positioned over it.
 * This is what replaces notebook-drawing's stage-manager: there is no viewport
 * stage, no scroll offset, and no prose-offset compensation, because a PDF
 * page does not move relative to its own content.
 *
 * Everything here works in PDF points and converts to screen only to draw.
 */
import Konva from 'konva';
import { buildStroke, hits } from './shapes.js';
import { screenToPdf } from './paged.js';

const ERASER_RADIUS = 6;   // PDF points

export class InkLayer {
  constructor(entry, { store, tools, gate }) {
    this.entry = entry;
    this.store = store;
    this.tools = tools;
    this.gate = gate;
    this.page = entry.number;

    const host = document.createElement('div');
    host.className = 'ink-layer';
    entry.el.appendChild(host);
    this.host = host;

    this.stage = new Konva.Stage({
      container: host,
      width: entry.viewport.width,
      height: entry.viewport.height,
    });
    this.layer = new Konva.Layer({ listening: false });
    this.stage.add(this.layer);
    this.scale = entry.viewport.scale;

    this._bind(host);
    this.redraw();
  }

  /** Pointer position in PDF points. */
  _point(event) {
    const rect = this.host.getBoundingClientRect();
    return screenToPdf(event.clientX - rect.left, event.clientY - rect.top,
                       { scale: this.scale });
  }

  _bind(host) {
    host.style.touchAction = 'none';

    const down = (event) => {
      this.gate.note(event);
      if (!this.gate.shouldDraw(event)) return;       // palm, or touch-to-pan
      if (this.tools.mode === 'select') return;
      event.preventDefault();
      host.setPointerCapture(event.pointerId);
      this.drawing = true;
      const at = this._point(event);
      this.from = at;
      this.points = [[at.x, at.y, event.pressure > 0 ? event.pressure : 0.5]];
      if (this.tools.mode === 'erase') this._eraseAt(at);
    };

    const move = (event) => {
      if (!this.drawing) return;
      // Coalesced events carry the samples the browser batched into this
      // frame. Without them a fast stroke is drawn as a polygon.
      const batch = event.getCoalescedEvents ? event.getCoalescedEvents() : [event];
      for (const sample of batch) {
        const at = this._point(sample);
        if (this.tools.mode === 'erase') { this._eraseAt(at); continue; }
        this.points.push([at.x, at.y,
                          sample.pressure > 0 ? sample.pressure : 0.5]);
        this.to = at;
      }
      this._preview();
    };

    const up = () => {
      if (!this.drawing) return;
      this.drawing = false;
      this._commit();
    };

    host.addEventListener('pointerdown', down);
    host.addEventListener('pointermove', move);
    host.addEventListener('pointerup', up);
    host.addEventListener('pointercancel', up);
    host.addEventListener('pointerleave', up);
  }

  _eraseAt(at) {
    const doomed = [];
    this.store.get(this.page).forEach((stroke, index) => {
      if (hits(stroke, at.x, at.y, ERASER_RADIUS)) doomed.push(index);
    });
    if (doomed.length) {
      this.store.removeAt(this.page, doomed);
      this.redraw();
    }
  }

  _current() {
    const { mode, color, size, opacity } = this.tools;
    if (mode === 'erase' || mode === 'select') return null;
    return buildStroke(mode, { points: this.points, from: this.from,
                               to: this.to || this.from, color, size, opacity });
  }

  _preview() {
    const stroke = this._current();
    if (!stroke) return;
    if (!this.preview) {
      this.preview = new Konva.Path({ listening: false });
      this.layer.add(this.preview);
    }
    this._style(this.preview, stroke);
    this.layer.batchDraw();
  }

  _commit() {
    const stroke = this._current();
    if (this.preview) { this.preview.destroy(); this.preview = null; }
    if (stroke && stroke.d) this.store.add(this.page, stroke);
    this.redraw();
  }

  /** Konva styling that matches what the PDF exporter will do. */
  _style(node, stroke) {
    node.data(stroke.d);
    node.scale({ x: this.scale, y: this.scale });
    node.opacity(stroke.opacity == null ? 1 : stroke.opacity);
    if (stroke.mode === 'stroke') {
      node.stroke(stroke.color);
      node.strokeWidth(stroke.width || 1);
      node.lineCap('round');
      node.lineJoin('round');
      node.fill(null);
    } else {
      node.fill(stroke.color);
      node.stroke(null);
    }
  }

  redraw() {
    this.layer.destroyChildren();
    for (const stroke of this.store.get(this.page)) {
      if (!stroke.d) continue;
      const node = new Konva.Path({ listening: false });
      this._style(node, stroke);
      this.layer.add(node);
    }
    this.preview = null;
    this.layer.batchDraw();
  }

  destroy() {
    this.stage.destroy();
    this.host.remove();
  }
}

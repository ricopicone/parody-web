/**
 * The ink for one section, keyed by page.
 *
 * Holds the whole document's strokes rather than one page's, because undo has
 * to cross pages: a reader who draws on page 2, scrolls to page 3, draws, then
 * hits undo twice expects both marks gone, in that order.
 */
const LIMIT = 50;

export class InkStore {
  constructor(strokes = {}, { onChange } = {}) {
    this.pages = { ...strokes };
    this.past = [];
    this.future = [];
    this.onChange = onChange || (() => {});
  }

  get(page) {
    return this.pages[String(page)] || [];
  }

  /** A snapshot for the undo stack. Cheap: strokes are small plain objects. */
  _snapshot() {
    return JSON.parse(JSON.stringify(this.pages));
  }

  _commit(next) {
    this.past.push(this._snapshot());
    if (this.past.length > LIMIT) this.past.shift();
    this.future.length = 0;
    this.pages = next;
    this.onChange(this.pages);
  }

  add(page, stroke) {
    const key = String(page);
    this._commit({ ...this.pages, [key]: [...this.get(page), stroke] });
  }

  /** Remove strokes by index. Used by the eraser and by delete-selection. */
  removeAt(page, indices) {
    if (!indices.length) return;
    const key = String(page);
    const drop = new Set(indices);
    this._commit({ ...this.pages,
                   [key]: this.get(page).filter((_, i) => !drop.has(i)) });
  }

  replaceAt(page, index, stroke) {
    const key = String(page);
    const next = [...this.get(page)];
    next[index] = stroke;
    this._commit({ ...this.pages, [key]: next });
  }

  clearPage(page) {
    this._commit({ ...this.pages, [String(page)]: [] });
  }

  undo() {
    if (!this.past.length) return false;
    this.future.push(this._snapshot());
    this.pages = this.past.pop();
    this.onChange(this.pages);
    return true;
  }

  redo() {
    if (!this.future.length) return false;
    this.past.push(this._snapshot());
    this.pages = this.future.pop();
    this.onChange(this.pages);
    return true;
  }

  get isEmpty() {
    return Object.values(this.pages).every((list) => !list.length);
  }

  toJSON() {
    // Drop empty pages so the payload does not grow a key per page visited.
    const out = {};
    for (const [key, list] of Object.entries(this.pages)) {
      if (list && list.length) out[key] = list;
    }
    return out;
  }
}

/**
 * The ink for one section, keyed by page.
 *
 * Holds the whole document's strokes rather than one page's, because undo has
 * to cross pages: a reader who draws on page 2, scrolls to page 3, draws, then
 * hits undo twice expects both marks gone, in that order.
 */
const LIMIT = 50;

export const PAGE = 'page';
export const PAD = 'pad';

export class InkStore {
  constructor(strokes = {}, { onChange, pads = {} } = {}) {
    // Two surfaces per page: the page itself, and the scratch pad beside it.
    // They share one history, because a reader who draws on the page, then in
    // the margin, then hits undo twice expects both gone in that order.
    this.surfaces = { [PAGE]: { ...strokes }, [PAD]: { ...pads } };
    this.past = [];
    this.future = [];
    this.onChange = onChange || (() => {});
  }

  get(page, surface = PAGE) {
    return this.surfaces[surface][String(page)] || [];
  }

  /** A snapshot for the undo stack. Cheap: strokes are small plain objects. */
  _snapshot() {
    return JSON.parse(JSON.stringify(this.surfaces));
  }

  _commit(next) {
    this.past.push(this._snapshot());
    if (this.past.length > LIMIT) this.past.shift();
    this.future.length = 0;
    this.surfaces = next;
    this.onChange(this.surfaces);
  }

  _with(surface, page, list) {
    return { ...this.surfaces,
             [surface]: { ...this.surfaces[surface], [String(page)]: list } };
  }

  add(page, stroke, surface = PAGE) {
    this._commit(this._with(surface, page, [...this.get(page, surface), stroke]));
  }

  /** Remove strokes by index. Used by the eraser and by delete-selection. */
  removeAt(page, indices, surface = PAGE) {
    if (!indices.length) return;
    const drop = new Set(indices);
    this._commit(this._with(surface, page,
                            this.get(page, surface).filter((_, i) => !drop.has(i))));
  }

  replaceAt(page, index, stroke, surface = PAGE) {
    const next = [...this.get(page, surface)];
    next[index] = stroke;
    this._commit(this._with(surface, page, next));
  }

  clearPage(page, surface = PAGE) {
    this._commit(this._with(surface, page, []));
  }

  undo() {
    if (!this.past.length) return false;
    this.future.push(this._snapshot());
    this.surfaces = this.past.pop();
    this.onChange(this.surfaces);
    return true;
  }

  redo() {
    if (!this.future.length) return false;
    this.past.push(this._snapshot());
    this.surfaces = this.future.pop();
    this.onChange(this.surfaces);
    return true;
  }

  get isEmpty() {
    return Object.values(this.surfaces).every(
      (surface) => Object.values(surface).every((list) => !list.length));
  }

  /** Does this page's margin have anything on it? Drives the pad's styling. */
  padUsed(page) {
    return this.get(page, PAD).length > 0;
  }

  _clean(surface) {
    // Drop empty pages so the payload does not grow a key per page visited.
    const out = {};
    for (const [key, list] of Object.entries(this.surfaces[surface])) {
      if (list && list.length) out[key] = list;
    }
    return out;
  }

  toJSON() {
    return this._clean(PAGE);
  }

  padsToJSON() {
    return this._clean(PAD);
  }
}

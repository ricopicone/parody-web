/**
 * Tool state.
 *
 * Every tool keeps its OWN width and opacity. An earlier version stored one
 * width for the whole toolbar and reset it only when switching to pen or
 * highlighter, so a line drawn after the highlighter came out 14pt and 35%
 * opaque, and the same line after the pen came out 2pt and solid — the width
 * you got depended on which tool you happened to use last, which is not
 * something a reader can predict or wants to think about.
 */

export const COLORS = ['#2563eb', '#dc2626', '#16a34a',
                       '#000000', '#f59e0b', '#8b5cf6'];

/**
 * Per-tool defaults and the widths each offers.
 *
 * A highlighter's useful widths are the height of a line of text; a pen's are
 * a fraction of that. Offering one list for both would mean most of it is
 * useless in either mode.
 */
export const TOOL_SPECS = {
  pen:         { size: 2,  opacity: 1,    widths: [1, 2, 3.5, 6] },
  highlighter: { size: 14, opacity: 0.35, widths: [8, 14, 20, 28] },
  line:        { size: 2,  opacity: 1,    widths: [1, 2, 3.5, 6] },
  rect:        { size: 2,  opacity: 1,    widths: [1, 2, 3.5, 6] },
  circle:      { size: 2,  opacity: 1,    widths: [1, 2, 3.5, 6] },
  erase:       { size: 12, opacity: 1,    widths: [6, 12, 24, 40] },
};

export const DRAW_MODES = ['pen', 'highlighter', 'line', 'rect', 'circle'];

export class Tools {
  constructor({ onChange } = {}) {
    this.mode = 'pen';
    this.color = COLORS[3];
    // One remembered width per tool, so switching tools never silently
    // changes the width of the one you are switching to.
    this.sizes = Object.fromEntries(
      Object.entries(TOOL_SPECS).map(([tool, spec]) => [tool, spec.size]));
    this.onChange = onChange || (() => {});
  }

  get spec() {
    return TOOL_SPECS[this.mode] || TOOL_SPECS.pen;
  }

  /** The current tool's width. */
  get size() {
    return this.sizes[this.mode] ?? this.spec.size;
  }

  /** Opacity belongs to the tool, not to the toolbar: only ink is translucent. */
  get opacity() {
    return this.spec.opacity;
  }

  get widths() {
    return this.spec.widths;
  }

  set(mode) {
    if (!TOOL_SPECS[mode]) return;
    this.mode = mode;
    this.onChange(this);
  }

  setColor(color) {
    this.color = color;
    this.onChange(this);
  }

  /** Sets the width of the CURRENT tool only. */
  setSize(size) {
    this.sizes[this.mode] = size;
    this.onChange(this);
  }
}

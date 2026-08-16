/**
 * Tool state and its controls.
 *
 * Keyboard shortcuts mirror the notebook-drawing engine so a reader who
 * already uses the HTML notebooks does not have to learn a second set:
 * d draw, e erase, s select, l line, r rect, c circle, 1-6 colours,
 * cmd/ctrl-z undo, shift-cmd/ctrl-z redo.
 */
export const COLORS = ['#2563eb', '#dc2626', '#16a34a',
                       '#000000', '#f59e0b', '#8b5cf6'];

const HIGHLIGHTER_OPACITY = 0.35;

export class Tools {
  constructor({ onChange } = {}) {
    this.mode = 'pen';
    this.color = COLORS[3];
    this.size = 2;
    this.opacity = 1;
    this.onChange = onChange || (() => {});
  }

  set(mode) {
    this.mode = mode;
    // A highlighter is a fat translucent pen; keeping it one tool rather than
    // a flag means the exporter and the store need know nothing about it.
    if (mode === 'highlighter') {
      this.opacity = HIGHLIGHTER_OPACITY;
      this.size = 14;
    } else if (mode === 'pen') {
      this.opacity = 1;
      this.size = 2;
    }
    this.onChange(this);
  }

  setColor(color) { this.color = color; this.onChange(this); }
  setSize(size) { this.size = size; this.onChange(this); }
}

export function bindKeys(tools, { undo, redo }) {
  const keys = { d: 'pen', h: 'highlighter', e: 'erase', s: 'select',
                 l: 'line', r: 'rect', c: 'circle' };
  window.addEventListener('keydown', (event) => {
    if (event.target.matches('input, textarea, [contenteditable]')) return;
    const meta = event.metaKey || event.ctrlKey;
    if (meta && event.key.toLowerCase() === 'z') {
      event.preventDefault();
      (event.shiftKey ? redo : undo)();
      return;
    }
    if (meta) return;
    const key = event.key.toLowerCase();
    if (keys[key]) { tools.set(keys[key]); event.preventDefault(); return; }
    const index = '123456'.indexOf(event.key);
    if (index >= 0) { tools.setColor(COLORS[index]); event.preventDefault(); }
  });
}

export function buildToolbar(root, tools, { undo, redo }) {
  root.innerHTML = '';
  const group = (label) => {
    const el = document.createElement('span');
    el.className = 'ink-tool-group';
    el.setAttribute('aria-label', label);
    return el;
  };

  const modes = group('tools');
  const buttons = [];
  for (const [mode, label, title] of [
    ['pen', '✎', 'Pen (d)'], ['highlighter', '▬', 'Highlighter (h)'],
    ['erase', '⌫', 'Eraser (e)'], ['line', '╱', 'Line (l)'],
    ['rect', '▭', 'Rectangle (r)'], ['circle', '◯', 'Ellipse (c)']]) {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = label;
    button.title = title;
    button.dataset.mode = mode;
    button.addEventListener('click', () => tools.set(mode));
    modes.appendChild(button);
    buttons.push(button);
  }
  root.appendChild(modes);

  const colors = group('colours');
  const swatches = [];
  COLORS.forEach((color, index) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'ink-swatch';
    button.style.background = color;
    button.title = `Colour ${index + 1}`;
    button.addEventListener('click', () => tools.setColor(color));
    colors.appendChild(button);
    swatches.push(button);
  });
  root.appendChild(colors);

  const history = group('history');
  for (const [label, title, action] of [['↶', 'Undo (⌘Z)', undo],
                                        ['↷', 'Redo (⇧⌘Z)', redo]]) {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = label;
    button.title = title;
    button.addEventListener('click', action);
    history.appendChild(button);
  }
  root.appendChild(history);

  const reflect = () => {
    buttons.forEach((b) => b.classList.toggle('is-on', b.dataset.mode === tools.mode));
    swatches.forEach((b, i) => b.classList.toggle('is-on', COLORS[i] === tools.color));
  };
  tools.onChange = reflect;
  reflect();
}

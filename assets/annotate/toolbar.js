/**
 * The toolbar: tools, colours, widths, history, zoom.
 *
 * Keyboard shortcuts mirror the notebook-drawing engine so a reader who uses
 * the HTML notebooks does not learn a second set: d draw, h highlighter,
 * e erase, l line, r rect, c circle, 1-6 colours, cmd/ctrl-z undo,
 * shift-cmd/ctrl-z redo, cmd/ctrl +/-/0 zoom.
 */
import { COLORS, DRAW_MODES } from './tools.js';
import { ICONS, widthIcon } from './icons.js';

const MODE_BUTTONS = [
  ['pen', 'Pen', 'd'],
  ['highlighter', 'Highlighter', 'h'],
  ['erase', 'Eraser', 'e'],
  ['line', 'Line', 'l'],
  ['rect', 'Rectangle', 'r'],
  ['circle', 'Ellipse', 'c'],
];

function button(html, title) {
  const el = document.createElement('button');
  el.type = 'button';
  el.innerHTML = html;
  el.title = title;
  el.setAttribute('aria-label', title);
  return el;
}

function group(label) {
  const el = document.createElement('span');
  el.className = 'ink-tool-group';
  el.setAttribute('role', 'group');
  el.setAttribute('aria-label', label);
  return el;
}

export function buildToolbar(root, tools, { undo, redo, zoomIn, zoomOut, zoomReset }) {
  root.innerHTML = '';

  const modes = group('Tools');
  const modeButtons = [];
  for (const [mode, label, key] of MODE_BUTTONS) {
    const el = button(ICONS[mode], `${label} (${key})`);
    el.dataset.mode = mode;
    el.addEventListener('click', () => tools.set(mode));
    modes.appendChild(el);
    modeButtons.push(el);
  }
  root.appendChild(modes);

  // Widths are rebuilt on every tool change: the useful widths for a
  // highlighter and for a pen do not overlap.
  const widths = group('Width');
  root.appendChild(widths);

  const colors = group('Colour');
  const swatches = COLORS.map((color, index) => {
    const el = button('', `Colour ${index + 1}`);
    el.className = 'ink-swatch';
    el.style.background = color;
    el.addEventListener('click', () => tools.setColor(color));
    colors.appendChild(el);
    return el;
  });
  root.appendChild(colors);

  const history = group('History');
  for (const [icon, title, action] of [[ICONS.undo, 'Undo (⌘Z)', undo],
                                       [ICONS.redo, 'Redo (⇧⌘Z)', redo]]) {
    const el = button(icon, title);
    el.addEventListener('click', action);
    history.appendChild(el);
  }
  root.appendChild(history);

  const zoom = group('Zoom');
  const zoomLabel = document.createElement('button');
  zoomLabel.type = 'button';
  zoomLabel.className = 'ink-zoom-level';
  zoomLabel.title = 'Reset zoom (⌘0)';
  zoomLabel.addEventListener('click', zoomReset);
  for (const [icon, title, action] of [[ICONS.zoomOut, 'Zoom out (⌘−)', zoomOut],
                                       [ICONS.zoomIn, 'Zoom in (⌘+)', zoomIn]]) {
    const el = button(icon, title);
    el.addEventListener('click', action);
    zoom.appendChild(el);
    if (el === zoom.firstChild) zoom.appendChild(zoomLabel);
  }
  root.appendChild(zoom);

  function renderWidths() {
    widths.innerHTML = '';
    if (tools.mode === 'erase') {
      widths.hidden = true;
      return;
    }
    widths.hidden = false;
    const max = Math.max(...tools.widths);
    for (const width of tools.widths) {
      const el = button(widthIcon(width, max), `Width ${width}`);
      el.className = 'ink-width';
      el.dataset.width = String(width);
      el.addEventListener('click', () => tools.setSize(width));
      widths.appendChild(el);
    }
  }

  function reflect() {
    modeButtons.forEach((el) =>
      el.classList.toggle('is-on', el.dataset.mode === tools.mode));
    swatches.forEach((el, i) =>
      el.classList.toggle('is-on', COLORS[i] === tools.color));
    // Colour is meaningless while erasing; say so rather than let a reader
    // pick one and wonder why nothing changed.
    colors.hidden = tools.mode === 'erase';
    renderWidths();
    widths.querySelectorAll('.ink-width').forEach((el) =>
      el.classList.toggle('is-on', Number(el.dataset.width) === tools.size));
  }

  tools.onChange = reflect;
  reflect();

  return {
    showZoom(percent) { zoomLabel.textContent = `${Math.round(percent)}%`; },
  };
}

export function bindKeys(tools, { undo, redo, zoomIn, zoomOut, zoomReset }) {
  const keys = { d: 'pen', h: 'highlighter', e: 'erase',
                 l: 'line', r: 'rect', c: 'circle' };
  window.addEventListener('keydown', (event) => {
    if (event.target.matches?.('input, textarea, select, [contenteditable]')) return;
    const meta = event.metaKey || event.ctrlKey;
    if (meta) {
      const key = event.key;
      if (key.toLowerCase() === 'z') {
        event.preventDefault();
        (event.shiftKey ? redo : undo)();
      } else if (key === '=' || key === '+') {
        event.preventDefault(); zoomIn();
      } else if (key === '-' || key === '_') {
        event.preventDefault(); zoomOut();
      } else if (key === '0') {
        event.preventDefault(); zoomReset();
      }
      return;
    }
    const key = event.key.toLowerCase();
    if (keys[key]) { tools.set(keys[key]); event.preventDefault(); return; }
    const index = '123456'.indexOf(event.key);
    if (index >= 0) { tools.setColor(COLORS[index]); event.preventDefault(); }
  });
}

export { COLORS, DRAW_MODES };

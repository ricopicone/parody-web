/**
 * Toolbar icons.
 *
 * Inline SVG rather than glyphs: the previous toolbar used characters like ▬
 * and ⌫ for the highlighter and eraser, which render differently on every
 * platform and read as nothing in particular. These are drawn on a 24-grid,
 * inherit currentColor, and are shaped so the pen, highlighter and eraser are
 * distinguishable at 16px — which is the whole job.
 */

const svg = (body, { fill = 'none' } = {}) =>
  `<svg viewBox="0 0 24 24" width="18" height="18" fill="${fill}" `
  + `stroke="currentColor" stroke-width="1.6" stroke-linecap="round" `
  + `stroke-linejoin="round" aria-hidden="true" focusable="false">${body}</svg>`;

export const ICONS = {
  // A nib: a narrow body tapering to a point, with the slit that says "pen".
  pen: svg(`
    <path d="M4 20.5 5.4 16 15.8 5.6a2.1 2.1 0 0 1 3 3L8.4 19z"/>
    <path d="M14.2 7.2 17 10"/>
    <path d="M5.4 16 8.4 19"/>`),

  // A chisel-tip marker: broad angled nib over the band it lays down.
  highlighter: svg(`
    <path d="M9 13.5 15.5 7a2 2 0 0 1 2.8 0l.7.7a2 2 0 0 1 0 2.8L12.5 17z"/>
    <path d="M9 13.5 12.5 17l-2.2 1.6H6.6z"/>
    <path d="M4 21.2h16" stroke-width="2.4" opacity=".45"/>`),

  // A block eraser on the page, tilted, with the rubbed line beneath it.
  erase: svg(`
    <path d="M8.6 18.4 4.4 14.2a1.8 1.8 0 0 1 0-2.6l7.2-7.2a1.8 1.8 0 0 1 2.6 0l5 5a1.8 1.8 0 0 1 0 2.6l-6.4 6.4z"/>
    <path d="M9 8.6 15.4 15"/>
    <path d="M4 21.2h16" opacity=".45"/>`),

  // A true diagonal with its endpoints marked — a line tool, not a slash.
  line: svg(`
    <path d="M6.8 17.2 17.2 6.8"/>
    <circle cx="5.6" cy="18.4" r="1.9"/>
    <circle cx="18.4" cy="5.6" r="1.9"/>`),

  rect: svg(`<rect x="4.2" y="6.2" width="15.6" height="11.6" rx="1.4"/>`),

  circle: svg(`<ellipse cx="12" cy="12" rx="7.8" ry="5.8"/>`),

  undo: svg(`
    <path d="M4.5 9.5h9a5 5 0 0 1 0 10H9"/>
    <path d="M8 5.5 4 9.5l4 4"/>`),

  redo: svg(`
    <path d="M19.5 9.5h-9a5 5 0 0 0 0 10H15"/>
    <path d="M16 5.5l4 4-4 4"/>`),

  // A printer: paper going in the top, the sheet coming out the front.
  print: svg(`
    <path d="M7 8.4V3.6h10v4.8"/>
    <path d="M7 17.4H5.4A1.6 1.6 0 0 1 3.8 15.8v-4.2a1.6 1.6 0 0 1 1.6-1.6h13.2a1.6 1.6 0 0 1 1.6 1.6v4.2a1.6 1.6 0 0 1-1.6 1.6H17"/>
    <path d="M7 14.2h10v6.2H7z"/>
    <path d="M6.4 12.4h1.4"/>`),

  // A hand: the finger-draw toggle, which is about the hand rather than the
  // pen. Index finger raised over a fist, drawn to read at 16px.
  finger: svg(`
    <path d="M10 11.4V5.2a1.6 1.6 0 0 1 3.2 0v6.2"/>
    <path d="M13.2 11.6V9.4a1.5 1.5 0 0 1 3 0v2.2"/>
    <path d="M16.2 11.8v-1.2a1.5 1.5 0 0 1 3 0v5.2a4.8 4.8 0 0 1-4.8 4.8h-2.1a4.5 4.5 0 0 1-3.5-1.7l-3.1-3.9a1.5 1.5 0 0 1 2.2-2l1.9 1.8"/>`),

  // A half-filled disc: the same idea as the site's own theme toggle.
  theme: svg(`
    <circle cx="12" cy="12" r="8.2"/>
    <path d="M12 3.8a8.2 8.2 0 0 0 0 16.4z" fill="currentColor" stroke="none"/>`),

  zoomIn: svg(`
    <circle cx="10.6" cy="10.6" r="6.4"/>
    <path d="M15.4 15.4 20.5 20.5"/>
    <path d="M10.6 8v5.2M8 10.6h5.2"/>`),

  zoomOut: svg(`
    <circle cx="10.6" cy="10.6" r="6.4"/>
    <path d="M15.4 15.4 20.5 20.5"/>
    <path d="M8 10.6h5.2"/>`),
};

/** A width swatch: a dot whose size is the width it selects. */
export function widthIcon(width, max) {
  const r = 2 + (width / max) * 6;
  return `<svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true" `
       + `focusable="false"><circle cx="10" cy="10" r="${r.toFixed(1)}" `
       + `fill="currentColor"/></svg>`;
}

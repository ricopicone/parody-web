/**
 * LaTeX in, spoken English out. Batched.
 *
 *   stdin :  {"items": [{"latex": "p(t)", "display": false}, ...]}
 *   stdout:  {"texts": ["p left parenthesis t right parenthesis", ...]}
 *
 * Batched deliberately: engine setup costs on the order of a second, and a
 * single chapter carries thousands of expressions, so one process per
 * expression would dominate generation time entirely.
 *
 * SRE speaks MathML, not LaTeX, so MathJax converts first.
 *
 * clearspeak, not mathspeak. Mathspeak is built for unambiguous dictation and
 * says "upper Z Subscript upper C Baseline"; clearspeak says "Z sub C", which
 * is what a lecturer says out loud. Its brief/sbrief styles are not an option
 * either way — those emit visual abbreviations ("p'ren", "Sub") meant for
 * braille displays, which a synthesiser reads as gibberish.
 *
 * Run only at generation time, from speech.py. A host that never regenerates
 * audio never needs Node — and if it is missing, SreMath falls back to silence
 * rather than failing.
 */
import { mathjax } from 'mathjax-full/js/mathjax.js';
import { TeX } from 'mathjax-full/js/input/tex.js';
import { liteAdaptor } from 'mathjax-full/js/adaptors/liteAdaptor.js';
import { RegisterHTMLHandler } from 'mathjax-full/js/handlers/html.js';
import { SerializedMmlVisitor } from 'mathjax-full/js/core/MmlTree/SerializedMmlVisitor.js';
import { AllPackages } from 'mathjax-full/js/input/tex/AllPackages.js';
import { STATE } from 'mathjax-full/js/core/MathItem.js';
import { SVG } from 'mathjax-full/js/output/svg.js';
import SRE from 'speech-rule-engine';

// bussproofs wants an output jax with getBBox(); we only ever go as far as
// MathML, so it would throw on every expression.
const PACKAGES = AllPackages.filter((name) => name !== 'bussproofs');

// ---------------------------------------------------------------------------
// Speech-only rewrites of the MathML tree. SRE takes an upright single letter
// (TeX's \Omega, \Phi, \mathrm{G}) as a possible UNIT and otherwise announces
// its font, so out of the box the books heard:
//
//   \Omega_J         "ohms sub J"        (System Dynamics' angular velocity)
//   \Phi(t)          "normal Phi of t"
//   \mathrm{dof}_G   "dof sub normal G"
//   0.8\ \Omega      "0.8 empty ohms"    (a TeX space is an mtext SRE reads)
//   2\ \mathrm{k}\Omega  "2 empty normal k ohms"
//   360^\circ        "360 raised to the composed with power"
//   \mathsf{v}_1      "sans serif v sub 1"; \mathfrak{m} "German m"
//
// A unit is a unit by where it sits: right after a number, possibly through a
// space or an SI prefix. Everywhere else an upright letter is a variable, and
// the font tells a listener nothing. Only the spoken tree is rewritten; the
// SVG a blank reveals is drawn from the expression as written.
// ---------------------------------------------------------------------------

const SPACE_TEXT = /^[\s  -​  　]*$/;
const SI_PREFIXES = new Set(['k', 'M', 'G', 'T', 'm', 'μ', 'µ', 'n', 'p']);
const SCRIPTS = new Set(['msub', 'msup', 'msubsup']);

// Parents, indexed from the root down. MathJax's own parent pointer is not to
// be trusted: TeX's `/` arrives as an mo inside a TeXAtom with NO parent,
// which silently cut 90^\circ/\mathrm{s} off from the number before it.
let PARENTS = new Map();

function indexParents(node) {
  for (const child of node.childNodes || []) {
    if (child && child.kind && child.kind !== 'text') {
      PARENTS.set(child, node);
      indexParents(child);
    }
  }
}

const parentOf = (node) => PARENTS.get(node) || null;

// The token a wrapper stands for: \mathrm{k} arrives as a one-child TeXAtom.
function lone(node) {
  while (node && !node.isToken && node.childNodes.length === 1) {
    node = node.childNodes[0];
  }
  return node;
}

// \, and \; arrive as an mspace inside an mstyle; \  and ~ as an mtext.
function isSpace(node) {
  const token = lone(node);
  return !!token && (token.isKind('mspace')
    || (token.isKind('mtext') && SPACE_TEXT.test(token.getText())));
}

// The node a token reads as, for its neighbours: out through one-child
// wrappers, and out of a script it is the base of (\mathrm{m}^2 is a unit).
function outer(node) {
  let at = node;
  for (;;) {
    const up = parentOf(at);
    if (!up || up.isKind('math')) return at;
    if (up.childNodes.length === 1 && !up.isToken) { at = up; continue; }
    if (SCRIPTS.has(up.kind) && up.childNodes[0] === at) { at = up; continue; }
    return at;
  }
}

// Only a row reads left to right. The T of R_2^{\mathrm{T}} sits after the
// 2 in an msubsup, but nothing about it follows a number.
// isKind, not .kind: a row TeX builds implicitly is an `inferredMrow`.
const ROWS = ['mrow', 'math', 'mstyle', 'TeXAtom', 'mpadded'];
const isRow = (node) => ROWS.some((kind) => node.isKind(kind));

// The nearest non-space token before `node` in its row.
function previous(node) {
  const at = outer(node);
  const row = parentOf(at);
  if (!row || !isRow(row)) return null;
  const siblings = row.childNodes;
  for (let i = siblings.indexOf(at) - 1; i >= 0; i--) {
    if (!isSpace(siblings[i])) return lone(siblings[i]);
  }
  return null;
}

// A number, or an expression made only of numbers: \frac{(1)(4)}{1+4}\ \text{k}\Omega
// and 10^{-3}\,\Omega carry their unit as surely as 4\ \Omega does.
const isDigits = (n) => n.isKind('mn') || (n.isKind('mi') && n.getText() === '\u03c0');

function isNumber(node) {
  if (!node) return false;
  if (node.isToken) return isDigits(node);
  let digits = 0;
  let other = 0;
  node.walkTree((n) => {
    if (!n.isToken) return;
    if (isDigits(n)) digits++;
    else if (!n.isKind('mo') && !isSpace(n)) other++;
  });
  return digits > 0 && other === 0;
}

// A bracketed run of numbers ending just before `node`: (1, 0, 1)\ \mathrm{m}.
// TeX's plain ( and ) are loose tokens in the row, not a group.
function afterNumericTuple(node) {
  const at = outer(node);
  const parent = parentOf(at);
  if (!parent || !isRow(parent)) return false;
  const row = parent.childNodes;
  let i = row.indexOf(at) - 1;
  while (i >= 0 && isSpace(row[i])) i--;
  const close = i >= 0 ? lone(row[i]) : null;
  if (!close || !close.isToken || !close.isKind('mo') || !/^[)\]]$/.test(close.getText())) {
    return false;
  }
  let depth = 0;
  let digits = 0;
  for (; i >= 0; i--) {
    const token = lone(row[i]);
    if (!token || !token.isToken) return false;
    const text = token.getText();
    if (token.isKind('mo') && /^[)\]]$/.test(text)) depth++;
    else if (token.isKind('mo') && /^[(\[]$/.test(text)) { if (--depth === 0) return digits > 0; }
    else if (isDigits(token)) digits++;
    else if (!token.isKind('mo') && !isSpace(token)) return false;
  }
  return false;
}

function isPrefix(node) {
  return !!node && (node.isKind('mi') || node.isKind('mtext'))
    && SI_PREFIXES.has(node.getText()) && isNumber(previous(node));
}

// Upright: a letter TeX set upright (\Omega, \mathrm{s}), or a multi-letter
// name, which is upright by default and carries no explicit variant (rad, kg).
function isUpright(node) {
  if (!node || !node.isKind('mi')) return false;
  const variant = node.attributes.getExplicit('mathvariant');
  return variant === 'normal'
    || (variant === undefined && [...node.getText()].length > 1);
}
const isLatinUpright = (node) => isUpright(node) && /^[A-Za-z]+$/.test(node.getText());
// Never a unit, wherever it sits: every Greek capital but Omega (20\,\Delta t),
// and the upright constants and operators e, d, i, j (2\,\mathrm{e}^{-t}).
const NEVER_UNITS = /^(?:[\u0391-\u03a8]|[edij])$/u;
const UNIT_JOINS = new Set(['/', '\u22c5', '\u00b7', '\u2219']);   // / and the dots

// Is this upright letter a unit, by where it sits?
//   after a number:            4\ \Omega, 10^{-3}\,\mathrm{s}, \pi\ \mathrm{s},
//                              (1, 0, 1)\ \mathrm{m}, 90^\circ/\mathrm{s}
//   after a unit, or a unit
//   and a / or a dot:          \mathrm{kg\,m^2}, \mathrm{rad/s}, \mathrm{N\,m/A}
//   in a \mathrm{} group with
//   other upright LATIN names: \mathrm{V\,s} said on its own (Greek does not
//                              count: {\Omega_1\Omega_2} is two variables)
function isUnit(node, seen = new Set()) {
  if (seen.has(node)) return false;
  seen.add(node);
  let before = previous(node);
  if (isNumber(before) || afterNumericTuple(node)) return true;
  if (before && before.isKind('mo') && UNIT_JOINS.has(before.getText())) {
    // 90^\circ/\mathrm{s}: per second, after a number as much as after a unit
    if (isNumber(previous(before))) return true;
    before = previous(before);
  }
  // \sin\Theta is not a unit chain: the name before has to be a unit itself.
  if (isUpright(before) && isUnit(before, seen)) return true;
  return inUnitGroup(node);
}

function inUnitGroup(node) {
  for (let up = parentOf(node); up && !up.isKind('math'); up = parentOf(up)) {
    if (up.isKind('TeXAtom')) {
      let upright = 0;
      up.walkTree((n) => { if (isLatinUpright(n)) upright++; });
      return upright > 1;
    }
  }
  return false;
}

function setText(token, text) {
  token.childNodes[0].setText(text);
}

function unsetVariant(node) {
  delete node.attributes.attributes.mathvariant;
}

function removeWrapped(node) {
  const at = outer(node);
  const up = parentOf(at);
  up.childNodes.splice(up.childNodes.indexOf(at), 1);
}

// Fonts that say nothing a listener can use. System Dynamics' \mathsf{v} and
// \mathsf{f} came out "sans serif v sub ..." 463 times, and robotics' mass
// \mathfrak{m} "German m sub ..." 344 times, which made the equations around
// them hard to follow. Bold stays (a vector beside its scalar) and so does
// script (\mathcal{V}, read "script V" in lectures too).
const QUIET_FONTS = new Map([
  ['sans-serif', null], ['sans-serif-italic', null], ['fraktur', null],
  ['bold-sans-serif', 'bold'], ['sans-serif-bold-italic', 'bold-italic'],
  ['bold-fraktur', 'bold'],
]);

function quietFont(node) {
  const font = node.attributes.getExplicit('mathvariant');
  if (!QUIET_FONTS.has(font)) return;
  const plain = QUIET_FONTS.get(font);
  if (plain) node.attributes.set('mathvariant', plain);
  else unsetVariant(node);
}

function forSpeech(root) {
  PARENTS = new Map();
  indexParents(root);
  const tokens = [];
  root.walkTree((node) => { if (node.isToken) tokens.push(node); });
  for (const node of tokens) {
    quietFont(node);
    if (node.isKind('mo') && node.getText() === '∘') {
      // ^\circ as a superscript is a degree sign, not function composition.
      const up = parentOf(outer(node));
      if (up && SCRIPTS.has(up.kind) && outer(node) !== up.childNodes[0]) {
        setText(node, '°');
      }
      continue;
    }
    if (!node.isKind('mi')) continue;
    if (node.attributes.getExplicit('mathvariant') !== 'normal') continue;
    const text = node.getText();
    if ([...text].length !== 1) continue;
    if (NEVER_UNITS.test(text)) {                    // \Delta, \mathrm{e}, \mathrm{d}
      unsetVariant(node);
      continue;
    }
    const before = previous(node);
    if (isPrefix(before)) {                          // 2 k Ω: one unit, kΩ
      setText(node, before.getText() + text);
      removeWrapped(before);
      continue;
    }
    if (isUnit(node)) continue;                      // 10 Ω, rad/s: a unit
    unsetVariant(node);                              // Ω_J, Φ(t): a variable
  }
  // A TeX space (\ , ~) is an mtext SRE reads as "empty". Only those go: an
  // mspace (\, \;) is NOT silent, it is SRE's cue for an explicit product —
  // without it "C\, dv/dt" loses its "times". Last, so the rules above could
  // still see past them.
  //
  // A wide mspace (\quad, \qquad: "R_1 \quad\text{and}", "\quad\Rightarrow\quad")
  // is read "empty" too, so it goes; the thin ones (\, \: \;) stay.
  const isTextSpace = (child) => {
    if (!isSpace(child)) return false;
    const token = lone(child);
    if (token.isKind('mtext')) return true;
    const width = /^([\d.]+)em$/.exec(String(token.attributes.get('width') || ''));
    return !!width && parseFloat(width[1]) >= 0.5;
  };
  root.walkTree((node) => {
    if (!node.isToken && node.childNodes.length) {
      const kept = node.childNodes.filter((child) => !isTextSpace(child));
      if (kept.length && kept.length !== node.childNodes.length) {
        node.childNodes.splice(0, node.childNodes.length, ...kept);
      }
    }
  });
  return root;
}

async function main() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  const { items = [], macros = {} } = JSON.parse(chunks.join('') || '{}');

  const adaptor = liteAdaptor();
  RegisterHTMLHandler(adaptor);
  const input = new TeX({ packages: PACKAGES, macros });
  const doc = mathjax.document('', { InputJax: input });
  // A second document with an output jax, for the picture the reader sees.
  // fontCache 'none' keeps each SVG self-contained, which it has to be: they
  // are embedded one per blank as data URIs, with no shared defs to point at.
  const svgDoc = mathjax.document('', {
    InputJax: new TeX({ packages: PACKAGES, macros }),
    OutputJax: new SVG({ fontCache: 'none' }),
  });
  const visitor = new SerializedMmlVisitor();
  // TriangleSymbol_Delta: clearspeak's default reads Δ as "triangle", so
  // Δt came out "triangle t". With this preference it is "Delta t".
  await SRE.setupEngine({ domain: 'clearspeak', style: 'TriangleSymbol_Delta',
                          locale: 'en' });

  const texts = items.map(({ latex, display }) => {
    try {
      const node = doc.convert(latex, { display: !!display, end: STATE.CONVERT });
      return SRE.toSpeech(visitor.visitTree(forSpeech(node)));
    } catch (err) {
      // One unparseable expression costs itself its narration, nothing more.
      return null;
    }
  });

  // Only clozes need a picture: a blank has to reveal the equation it hides,
  // and the reader is looking at a PDF canvas with no MathJax on the page.
  const svgs = items.map(({ latex, display, render }) => {
    if (!render) return null;
    try {
      const node = svgDoc.convert(latex, { display: !!display });
      const svg = adaptor.innerHTML(node);
      const match = /<svg[\s\S]*<\/svg>/.exec(svg);
      return match ? match[0] : null;
    } catch (err) {
      return null;
    }
  });

  process.stdout.write(JSON.stringify({ texts, svgs }));
}

main().catch((err) => {
  process.stderr.write(String(err && err.message));
  process.exit(1);
});

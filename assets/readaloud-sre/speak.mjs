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
// them hard to follow. Bold and italic went too (task 981, Rico: "the slight
// ambiguity introduced is worth the natural reading") — "bold italic x of t"
// 414 times, mostly System Dynamics' \bm{x}. Script stays (\mathcal{V} beside
// V, read "script V" in lectures too), and so does double-struck (\mathbb{R}
// is "the real numbers").
const QUIET_FONTS = new Map([
  ['sans-serif', null], ['sans-serif-italic', null], ['fraktur', null],
  ['bold', null], ['italic', null], ['bold-italic', null],
  ['bold-sans-serif', null], ['sans-serif-bold-italic', null],
  ['bold-fraktur', null], ['bold-script', 'script'],
]);

function quietFont(node) {
  const font = node.attributes.getExplicit('mathvariant');
  if (!QUIET_FONTS.has(font)) return;
  const plain = QUIET_FONTS.get(font);
  if (plain) node.attributes.set('mathvariant', plain);
  else unsetVariant(node);
}

// ---------------------------------------------------------------------------
// Read as a lecturer reads it: Rico's listening notes on Puck (task 981).
// Each rewrite is decided by the expression around a symbol, which is why it
// is here and not in speech.py (which renames SRE's words for a symbol alone).
// ---------------------------------------------------------------------------

const INVISIBLE_TIMES = '⁢';

// The nearest non-space neighbour of `node` in its row, one way or the other:
// the row's children, the neighbour's index in them, and its token.
function neighbour(node, step) {
  const at = outer(node);
  const row = parentOf(at);
  if (!row || !isRow(row)) return null;
  const siblings = row.childNodes;
  for (let i = siblings.indexOf(at) + step; i >= 0 && i < siblings.length; i += step) {
    if (!isSpace(siblings[i])) return { row: siblings, index: i, token: lone(siblings[i]) };
  }
  return null;
}

// d or ∂, or a power of one (d^2 x): where a differential starts.
function isDifferential(node) {
  let token = lone(node);
  if (token && token.isKind('msup')) token = lone(token.childNodes[0]);
  return !!token && token.isToken && token.isKind('mi')
    && /^[d∂]$/u.test(token.getText());
}

// The parts of a fraction's numerator or denominator, spaces aside.
function members(node) {
  let at = node;
  while (at && !at.isToken && isRow(at) && at.childNodes.length === 1) at = at.childNodes[0];
  if (!at) return [];
  if (at.isToken || !isRow(at)) return [at];
  return at.childNodes.filter((child) => !isSpace(child));
}

// d h over d t, ∂f/∂x, d over dt: differentials over differentials. A
// lecturer says "d h d t" — no word between — and "slash" (SRE's word for an
// inline one after a letter it takes for a function) was the worst of all.
function isDerivative(numerator, denominator) {
  const top = members(numerator);
  const bottom = members(denominator);
  return top.length >= 1 && top.length <= 2 && isDifferential(top[0])
    && (top.length === 1 || !isDifferential(top[1]))
    && bottom.length >= 2 && bottom.length % 2 === 0
    && bottom.every((part, i) => (i % 2 === 0) === isDifferential(part));
}

// A thin space (\, \: \;) is SRE's cue for an explicit product — but not once
// a fraction has become a row: SRE folds the row into one implied product and
// the "times" goes ("d theta d s s dot" for \frac{d\theta}{ds}\,\dot{s}). So
// a thin space beside a rewritten derivative becomes the times it was read as.
function isThinSpace(node) {
  if (!isSpace(node)) return false;
  const token = lone(node);
  if (!token.isKind('mspace')) return false;
  const width = /^([\d.]+)em$/.exec(String(token.attributes.get('width') || ''));
  return !width || parseFloat(width[1]) < 0.5;
}

function timesBeside(row, at, factory) {
  const index = row.childNodes.indexOf(at);
  for (const i of [index - 1, index + 1]) {
    if (i < 0 || i >= row.childNodes.length || !isThinSpace(row.childNodes[i])) continue;
    const times = factory.create('mo');
    times.appendChild(factory.create('text').setText('⋅'));
    row.replaceChild(times, row.childNodes[i]);
  }
}

// \frac{dh}{dt} becomes "d h", an invisible times, "d t". The invisible times
// keeps SRE from reading "d f d t" as f applied to "d t" ("d f of d t").
function speakDerivativeFractions(root) {
  const fractions = [];
  root.walkTree((node) => { if (node.isKind('mfrac')) fractions.push(node); });
  for (const fraction of fractions) {
    const [numerator, denominator] = fraction.childNodes;
    if (!isDerivative(numerator, denominator)) continue;
    const up = parentOf(fraction) || fraction.parent;
    if (!up) continue;
    const { factory } = fraction;
    const times = factory.create('mo');
    times.appendChild(factory.create('text').setText(INVISIBLE_TIMES));
    const read = factory.create('mrow', {}, [numerator, times, denominator]);
    up.replaceChild(read, fraction);
    if (isRow(up)) timesBeside(up, read, factory);
  }
}

// The same written inline, d\theta/dt or d/dt: only the slash goes.
function speakDerivativeSlashes(tokens) {
  for (const node of tokens) {
    if (!node.isKind('mo') || node.getText() !== '/') continue;
    const before = neighbour(node, -1);
    const after = neighbour(node, +1);
    if (!before || !after) continue;
    // d/dt: a lone differential on top; dh/dt: a differential, then one thing.
    const first = neighbour(before.row[before.index], -1);
    const numerator = isDifferential(before.token)
      || (!!first && isDifferential(first.token));
    const second = neighbour(after.row[after.index], +1);
    const denominator = isDifferential(after.token)
      && !!second && !isDifferential(second.token);
    if (numerator && denominator) setText(node, INVISIBLE_TIMES);
  }
}

// × is "cross" unless the expression says otherwise (Rico: "almost always the
// explicit times symbol is cross product"). The engine reads it "cross"
// (MultsymbolX_Cross); this decides the exceptions, measured over every ×
// the voiced books speak:
//   by     a dimension:  3 × 3, m × n, \mathbb{R}^{6 × n}, I_{n × n},
//                        n × n\ \text{matrix}
//   times  beside a number: 3.3 × 10^{-5}, 0.30 × 4, (0, 0.9, 0) × 0.5, (-2) × 10
//   cross  the rest:     ω × v, r × f, (0, 0, 1) × (1, -2, 0), \mathbb{R}^2 × S^1
const isInteger = (n) => !!n && n.isKind('mn') && /^\d+$/.test(n.getText());
const isDimensionLetter = (n) => !!n && n.isKind('mi') && /^[mnkr]$/.test(n.getText())
  && n.attributes.getExplicit('mathvariant') === undefined;
const isDimension = (n) => isInteger(n) || isDimensionLetter(n);

function inScript(node) {
  for (let at = node, up = parentOf(node); up && !up.isKind('math'); at = up, up = parentOf(up)) {
    if (SCRIPTS.has(up.kind) && up.childNodes[0] !== at) return true;
  }
  return false;
}

// The whole expression is "a × b".
function standsAlone(node) {
  const row = parentOf(outer(node));
  if (!row) return false;
  const top = row.isKind('math') || (parentOf(row) && parentOf(row).isKind('math'));
  return !!top && row.childNodes.filter((child) => !isSpace(child)).length === 3;
}

// "n × n matrix": the product is followed by the word.
function namesAMatrix(side) {
  const next = neighbour(side.row[side.index], +1);
  return !!next && next.token.isKind('mtext') && /^\s*(matri|array)/i.test(next.token.getText());
}

// A number, a power of one (10^{-6}), or a bracketed number such as (-2) —
// but not a tuple: (0, 0, 1) × (1, -2, 0) is a cross product.
function isNumeric(side, step) {
  if (!side) return false;
  const { token } = side;
  if (token.isKind('mn')) return true;
  if (token.isKind('msup') || token.isKind('msub')) {
    const base = lone(token.childNodes[0]);
    return !!base && base.isKind('mn');
  }
  const closing = step < 0 ? /^[)\]]$/ : /^[(\[]$/;
  const opening = step < 0 ? /^[(\[]$/ : /^[)\]]$/;
  if (!token.isKind('mo') || !closing.test(token.getText())) return false;
  let depth = 0;
  let digits = 0;
  for (let i = side.index; i >= 0 && i < side.row.length; i += step) {
    const part = lone(side.row[i]);
    if (!part || !part.isToken) return false;
    const text = part.getText();
    if (part.isKind('mo') && closing.test(text)) depth++;
    else if (part.isKind('mo') && opening.test(text)) { if (--depth === 0) return digits > 0; }
    else if (part.isKind('mn')) digits++;
    else if (text === ',' || !(part.isKind('mo') || isSpace(part))) return false;
  }
  return false;
}

function speakTimes(tokens) {
  for (const node of tokens) {
    if (!node.isKind('mo') || node.getText() !== '×') continue;
    const left = neighbour(node, -1);
    const right = neighbour(node, +1);
    const l = left && left.token;
    const r = right && right.token;
    if (isDimension(l) && isDimension(r)
        && (inScript(node) || standsAlone(node) || namesAMatrix(right)
            || (isDimensionLetter(l) && isDimensionLetter(r)))) {
      setText(node, 'by');
    } else if (isNumeric(left, -1) || isNumeric(right, +1)) {
      setText(node, '⋅');                      // read "times"
    }
  }
}

// R^{\mathrm{T}}, q^{\mathsf{T}}, x^\top: a transpose. SRE read them "R to
// the T power" (252 times in robotics) and "raised to the down tack power"
// (System Dynamics' \top); each becomes a ⊤ here, and speech.py says
// "transpose". An italic T stays a power: \int_0^T. J^{-\mathrm{T}} is
// "J inverse transpose".
function isTransposeMark(token) {
  if (!token || !token.isToken) return false;
  const text = token.getText();
  const variant = token.attributes.getExplicit('mathvariant');
  return text === '⊤' || text === '⊺'
    || (text === 'T' && (variant === 'normal' || variant === 'sans-serif'));
}

function markTransposes(root) {
  root.walkTree((node) => {
    if (!node.isKind('msup') && !node.isKind('msubsup')) return;
    let mark = lone(node.childNodes[node.sup]);
    if (mark && !mark.isToken && isRow(mark)) {             // ^{-\mathrm{T}}
      const parts = members(mark);
      const minus = parts.length === 2 && lone(parts[0]);
      mark = minus && minus.isKind('mo') && /^[-−]$/.test(minus.getText())
        ? lone(parts[1]) : null;
    }
    if (!isTransposeMark(mark)) return;
    setText(mark, '⊤');
    unsetVariant(mark);
  });
}

// c_{11} is "c one one", the way a matrix entry is read, not "c eleven".
function spellSubscriptDigits(root) {
  root.walkTree((node) => {
    if (!node.isKind('msub') && !node.isKind('msubsup')) return;
    const base = lone(node.childNodes[0]);
    if (base && base.isKind('mo')) return;          // \sum_{10}: a limit
    const sub = lone(node.childNodes[node.sub]);
    if (sub && sub.isToken && sub.isKind('mn') && /^\d{2,}$/.test(sub.getText())) {
      setText(sub, [...sub.getText()].join(' '));
    }
  });
}

// \dot{\theta}_1 is "theta 1 dot" (Rico, task 981), not "theta dot sub 1".
// The dot is set on the symbol so the subscripts line up, but it is the
// derivative of the subscripted quantity, and that is read first. So
// msub(mover(θ, ˙), 1) becomes mover(msub(θ, 1), ˙), which SRE reads in that
// order; an msubsup keeps its superscript outside: \dot{\theta}_1^2 is
// "theta 1 dot squared". A compound subscript keeps the dot before it: SRE
// never says where a subscript ends, and "beta sub j plus 1 dot" would hang
// the dot on the 1.
const DOTS = new Set(['\u02d9', '\u00a8', '\u20db', '\u20dc']);   // \dot … \ddddot

function dotted(node) {
  const over = lone(node);
  if (!over || !over.isKind('mover')) return null;
  const mark = lone(over.childNodes[over.over]);
  return mark && mark.isKind('mo') && DOTS.has(mark.getText()) ? over : null;
}

// One symbol, a word in \text{}, or a run of letters and digits (T_{sb}).
function isSimpleSubscript(node) {
  const isPlain = (token) => !!token && token.isToken
    && (token.isKind('mi') || token.isKind('mn') || token.isKind('mtext'));
  const sub = lone(node);
  if (!sub) return false;
  if (sub.isToken) return isPlain(sub);
  return isRow(sub) && members(sub).every((part) => isPlain(lone(part)));
}

function speakDotsAfterSubscripts(root) {
  const scripts = [];
  // .kind, not isKind: an msub and an msup are each an isKind('msubsup').
  root.walkTree((node) => {
    if (node.kind === 'msub' || node.kind === 'msubsup') scripts.push(node);
  });
  for (const script of scripts) {
    const over = dotted(script.childNodes[0]);
    if (!over || !isSimpleSubscript(script.childNodes[script.sub])) continue;
    const up = parentOf(script) || script.parent;
    if (!up) continue;
    const { factory } = script;
    const base = over.childNodes[over.base];
    over.replaceChild(factory.create('msub', {}, [base, script.childNodes[script.sub]]), base);
    let read = script.childNodes[0];                 // the dotted base, now subscripted
    if (script.kind === 'msubsup') {
      read = factory.create('msup', {}, [read, script.childNodes[script.sup]]);
    }
    up.replaceChild(read, script);
  }
}

function reindex(root) {
  PARENTS = new Map();
  indexParents(root);
}

function forSpeech(root) {
  reindex(root);
  speakDotsAfterSubscripts(root);
  reindex(root);                                     // the tree changed
  speakDerivativeFractions(root);
  reindex(root);
  markTransposes(root);
  spellSubscriptDigits(root);
  const tokens = [];
  root.walkTree((node) => { if (node.isToken) tokens.push(node); });
  speakDerivativeSlashes(tokens);
  speakTimes(tokens);
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
  // MultsymbolX_Cross: × is "cross" — speakTimes() turns the ones that are
  // not into a "times" or a "by" first.
  await SRE.setupEngine({ domain: 'clearspeak',
                          style: 'TriangleSymbol_Delta:MultsymbolX_Cross',
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

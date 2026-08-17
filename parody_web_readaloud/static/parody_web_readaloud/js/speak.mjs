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
  await SRE.setupEngine({ domain: 'clearspeak', style: 'default', locale: 'en' });

  const texts = items.map(({ latex, display }) => {
    try {
      const node = doc.convert(latex, { display: !!display, end: STATE.CONVERT });
      return SRE.toSpeech(visitor.visitTree(node));
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

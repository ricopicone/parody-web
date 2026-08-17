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
 * SRE speaks MathML, not LaTeX, so MathJax converts first. Style is
 * mathspeak/default rather than brief or sbrief: the terse styles emit visual
 * abbreviations ("p'ren", "Sub", "Base") which are meant for braille and
 * displays, and a speech synthesiser reads them as gibberish.
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
import SRE from 'speech-rule-engine';

// bussproofs wants an output jax with getBBox(); we only ever go as far as
// MathML, so it would throw on every expression.
const PACKAGES = AllPackages.filter((name) => name !== 'bussproofs');

async function main() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  const { items = [], macros = {} } = JSON.parse(chunks.join('') || '{}');

  RegisterHTMLHandler(liteAdaptor());
  const doc = mathjax.document('', {
    InputJax: new TeX({ packages: PACKAGES, macros }),
  });
  const visitor = new SerializedMmlVisitor();
  await SRE.setupEngine({ domain: 'mathspeak', style: 'default', locale: 'en' });

  const texts = items.map(({ latex, display }) => {
    try {
      const node = doc.convert(latex, { display: !!display, end: STATE.CONVERT });
      return SRE.toSpeech(visitor.visitTree(node));
    } catch (err) {
      // One unparseable expression costs itself its narration, nothing more.
      return null;
    }
  });

  process.stdout.write(JSON.stringify({ texts }));
}

main().catch((err) => {
  process.stderr.write(String(err && err.message));
  process.exit(1);
});

/**
 * Build the annotator bundle.
 *
 * The output is COMMITTED and shipped in the wheel: a host installs
 * parody-web with pip and must never need Node. Run this only when the
 * sources under assets/annotate/ change.
 */
import { build } from 'esbuild';
import { copyFile, mkdir } from 'node:fs/promises';

const OUT = 'parody_web_annotate/static/parody_web_annotate/js';

await mkdir(OUT, { recursive: true });

await build({
  entryPoints: ['assets/annotate/index.js'],
  bundle: true,
  minify: true,
  format: 'esm',
  target: ['es2020'],
  outfile: `${OUT}/annotate.js`,
  logLevel: 'info',
});

// pdf.js insists on a separate worker file; it cannot be inlined into the
// bundle, so it is copied beside it and pointed at from the template.
await copyFile('node_modules/pdfjs-dist/build/pdf.worker.min.mjs',
               `${OUT}/pdf.worker.mjs`);
console.log(`copied pdf.worker.mjs -> ${OUT}`);

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

// Read-along ships as its OWN bundle rather than joining the annotator's: they
// are separate Django apps, a host may install either alone, and a shared
// bundle would turn read-along's absence into a missing-module error in the
// annotator.
const READALOUD_OUT = 'parody_web_readaloud/static/parody_web_readaloud/js';
await mkdir(READALOUD_OUT, { recursive: true });
await build({
  entryPoints: ['assets/readaloud/index.js'],
  bundle: true,
  minify: true,
  format: 'esm',
  target: ['es2020'],
  outfile: `${READALOUD_OUT}/readalong.js`,
  logLevel: 'info',
});

// pdf.js insists on a separate worker file; it cannot be inlined into the
// bundle, so it is copied beside it and pointed at from the template.
//
// Copied to .js, NOT .mjs, even though its contents are a module. Python's
// mimetypes does not know .mjs, so Django and whitenoise serve it as
// application/octet-stream — and a module import is strictly MIME-checked, so
// the browser refuses it and the viewer renders nothing. Found in production.
// Fixing it here means no host has to learn this.
await copyFile('node_modules/pdfjs-dist/build/pdf.worker.min.mjs',
               `${OUT}/pdf.worker.js`);
console.log(`copied pdf.worker.js -> ${OUT}`);

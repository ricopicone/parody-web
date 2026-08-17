import test from 'node:test';
import assert from 'node:assert/strict';
import { printUrl } from './print.js';

test('prints the annotated copy when the reader has notes', () => {
  assert.equal(printUrl({ dataset: { downloadUrl: '/a/pdf/annotated/',
                                     pdfUrl: '/a/pdf/at/' } }),
               '/a/pdf/annotated/');
});

test('falls back to the plain pdf when there are none', () => {
  assert.equal(printUrl({ dataset: { pdfUrl: '/a/pdf/at/' } }), '/a/pdf/at/');
});

test('an empty download url is not treated as a url', () => {
  assert.equal(printUrl({ dataset: { downloadUrl: '', pdfUrl: '/a/pdf/at/' } }),
               '/a/pdf/at/');
});

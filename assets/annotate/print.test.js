import test from 'node:test';
import assert from 'node:assert/strict';
import { printUrl } from './print.js';

test('prints the annotated copy when the reader has notes', () => {
  assert.equal(printUrl({ dataset: { downloadUrl: '/a/pdf/annotated/',
                                     pdfUrl: '/a/pdf/at/' } }),
               '/a/pdf/annotated/?inline=1');
});

test('falls back to the plain pdf when there are none', () => {
  assert.equal(printUrl({ dataset: { pdfUrl: '/a/pdf/at/' } }),
               '/a/pdf/at/?inline=1');
});

test('always asks for the document inline', () => {
  // Without this the endpoint sends Content-Disposition: attachment, the
  // iframe downloads the file instead of rendering it, and Print silently
  // saves a copy with no dialog.
  for (const u of ['/a/pdf/annotated/', '/a/pdf/at/?v=abc']) {
    assert.match(printUrl({ dataset: { pdfUrl: u } }), /[?&]inline=1$/);
  }
});

test('an existing query string is kept', () => {
  assert.equal(printUrl({ dataset: { downloadUrl: '/a/pdf/annotated/?v=abc' } }),
               '/a/pdf/annotated/?v=abc&inline=1');
});

test('an empty download url is not treated as a url', () => {
  assert.equal(printUrl({ dataset: { downloadUrl: '', pdfUrl: '/a/pdf/at/' } }),
               '/a/pdf/at/?inline=1');
});

test('no url at all stays falsy rather than becoming "?inline=1"', () => {
  assert.equal(printUrl({ dataset: {} }), undefined);
});

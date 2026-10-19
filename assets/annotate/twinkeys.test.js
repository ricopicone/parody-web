import test from 'node:test';
import assert from 'node:assert/strict';
import { keysToSend, twinInkToSend, twinIsStale } from './twinkeys.js';

test('ink written over other pages than these is stale', () => {
  assert.equal(twinIsStale({ de: 'old' }, 'de', 'new', true), true);
  assert.equal(twinIsStale({ de: 'new' }, 'de', 'new', true), false);
});

test('no ink, no key, or no translation shown is never stale', () => {
  assert.equal(twinIsStale({ de: 'old' }, 'de', 'new', false), false);
  assert.equal(twinIsStale({}, 'de', 'new', true), false);
  assert.equal(twinIsStale({ de: 'old' }, '', '', true), false);
});

test('the language shown takes the current key once written on', () => {
  assert.deepEqual(keysToSend({ de: 'old', zh: 'z' }, 'de', 'new', { hadInk: true, touched: true }),
                   { de: 'new' });
});

test('ink not touched keeps the key it was written over: nothing is sent', () => {
  // an English stroke saves the layer too; that must not clear the warning
  assert.equal(keysToSend({ de: 'old' }, 'de', 'new', { hadInk: true, touched: false }), undefined);
});

test('a language with nothing on it yet takes the current key', () => {
  assert.deepEqual(keysToSend({}, 'de', 'new', { hadInk: false, touched: false }), { de: 'new' });
  assert.equal(keysToSend(undefined, '', '', { hadInk: false, touched: false }), undefined);
});

test('only the translation shown is sent, never the others', () => {
  // The server replaces each language sent. Sending every language loaded let
  // an English-only tab, or a tab on the other language, erase notes written
  // since it opened.
  const all = { de: { 1: ['a'] }, zh: { 2: ['b'] } };
  assert.deepEqual(twinInkToSend(all, 'zh'), { zh: { 2: ['b'] } });
  assert.equal(twinInkToSend(all, ''), undefined);
});

test('a translation erased to nothing is sent empty, so it is cleared', () => {
  assert.deepEqual(twinInkToSend({ de: { 1: ['a'] } }, 'zh'), { zh: {} });
});

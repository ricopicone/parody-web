import test from 'node:test';
import assert from 'node:assert/strict';
import { keysToSave, twinIsStale } from './twinkeys.js';

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
  assert.deepEqual(keysToSave({ de: 'old', zh: 'z' }, 'de', 'new', { hadInk: true, touched: true }),
                   { de: 'new', zh: 'z' });
});

test('ink not touched keeps the key it was written over', () => {
  // an English stroke saves the layer too; that must not clear the warning
  assert.deepEqual(keysToSave({ de: 'old' }, 'de', 'new', { hadInk: true, touched: false }),
                   { de: 'old' });
});

test('a language with nothing on it yet takes the current key', () => {
  assert.deepEqual(keysToSave({}, 'de', 'new', { hadInk: false, touched: false }), { de: 'new' });
  assert.deepEqual(keysToSave(undefined, '', '', { hadInk: false, touched: false }), {});
});

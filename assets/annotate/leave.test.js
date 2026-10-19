import test from 'node:test';
import assert from 'node:assert/strict';
import { leaveAfterSaving } from './leave.js';

test('notes not yet saved are saved before the page changes', async () => {
  // switching translation right after a stroke left the save in flight as
  // the page unloaded, and the browser asked "Leave site?"
  const order = [];
  await leaveAfterSaving('?twin=de', {
    unsaved: () => true,
    saveNow: async () => { order.push('save'); return true; },
    go: (href) => order.push(`go ${href}`),
  });
  assert.deepEqual(order, ['save', 'go ?twin=de']);
});

test('nothing unsaved: straight there', async () => {
  const order = [];
  await leaveAfterSaving('?twin=en', {
    unsaved: () => false,
    saveNow: async () => { order.push('save'); return true; },
    go: (href) => order.push(`go ${href}`),
  });
  assert.deepEqual(order, ['go ?twin=en']);
});

test('a save that fails still goes, and the page warns as it leaves', async () => {
  const order = [];
  await leaveAfterSaving('?v=old', {
    unsaved: () => true,
    saveNow: async () => { order.push('save'); return false; },
    go: (href) => order.push(`go ${href}`),
  });
  assert.deepEqual(order, ['save', 'go ?v=old']);
});

test('a save that never answers does not hold the reader for long', async () => {
  const order = [];
  await leaveAfterSaving('?twin=de', {
    unsaved: () => true,
    saveNow: () => new Promise(() => {}),
    go: (href) => order.push(`go ${href}`),
    waitMs: 20,
  });
  assert.deepEqual(order, ['go ?twin=de']);
});

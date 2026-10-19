import test from 'node:test';
import assert from 'node:assert/strict';
import { Edits } from './edits.js';

test('a save that carried every edit leaves nothing unsaved', () => {
  const edits = new Edits();
  edits.change();
  const sent = edits.stamp();
  assert.equal(edits.unsaved, true);
  edits.landed(sent);
  assert.equal(edits.unsaved, false);
});

test('a stroke drawn while a save was in flight is still unsaved when it lands', () => {
  // Any finished save cleared "dirty", so a stroke made during it, waiting
  // out its debounce, looked saved: switching translation left without it.
  const edits = new Edits();
  edits.change();                 // stroke A
  const sentA = edits.stamp();    // its save goes out
  edits.change();                 // stroke B, while A's save is in flight
  edits.landed(sentA);            // A's save lands
  assert.equal(edits.unsaved, true);
  edits.landed(edits.stamp());    // B's save
  assert.equal(edits.unsaved, false);
});

test('an older save landing late does not undo a newer one', () => {
  const edits = new Edits();
  edits.change();
  const first = edits.stamp();
  edits.change();
  const second = edits.stamp();
  edits.landed(second);
  edits.landed(first);
  assert.equal(edits.unsaved, false);
});

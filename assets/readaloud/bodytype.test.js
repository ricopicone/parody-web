import { strict as assert } from 'node:assert';
import { test } from 'node:test';
import { bodyType } from './bodytype.js';

const line = (token, h = 15) => ({ token, y0: 100, y1: 100 + h });

test('measures the body type off prose lines', () => {
  const track = { words: [line(0), line(1), line(2)], regions: [], clozes: [] };
  assert.equal(+bodyType(track).toFixed(2), 9.9);
});

test('a display equation does not stretch the type size', () => {
  // One equation token, narrated over many words, every one of them carrying
  // the tall box that spans the whole derivation — and more of them than there
  // is prose, which is ordinary in a worked section.
  const words = [line(0), line(1)];
  for (let i = 0; i < 40; i += 1) words.push(line(9, 180));
  const track = { words, regions: [{ token: 9 }], clozes: [] };
  assert.equal(+bodyType(track).toFixed(2), 9.9,
               'the reveal was three times the size of the page');
});

test('a cloze rule does not shrink it either', () => {
  const words = [line(0), line(1)];
  for (let i = 0; i < 40; i += 1) words.push(line(7, 0.4));
  const track = { words, regions: [], clozes: [{ token: 7 }] };
  assert.equal(+bodyType(track).toFixed(2), 9.9);
});

test('a section of nothing but maths still gets a size', () => {
  const track = { words: [line(9, 30), line(9, 30)],
                  regions: [{ token: 9 }], clozes: [] };
  assert.equal(+bodyType(track).toFixed(2), 19.8);
});

test('no geometry at all falls back rather than throwing', () => {
  assert.equal(+bodyType({ words: [] }).toFixed(2), 9.9);
  assert.equal(+bodyType(null).toFixed(2), 9.9);
});

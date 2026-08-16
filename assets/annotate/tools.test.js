import test from 'node:test';
import assert from 'node:assert/strict';
import { Tools, TOOL_SPECS } from './tools.js';

test('each tool keeps its own width', () => {
  const t = new Tools();
  t.set('pen'); t.setSize(6);
  t.set('line');
  assert.equal(t.size, TOOL_SPECS.line.size, 'line kept its own width');
  t.set('pen');
  assert.equal(t.size, 6, 'the pen remembered mine');
});

test('a shape does not inherit the highlighter width', () => {
  // The reported bug: line after highlighter came out 14pt and translucent.
  const t = new Tools();
  t.set('highlighter');
  assert.equal(t.size, 14);
  assert.equal(t.opacity, 0.35);
  t.set('line');
  assert.equal(t.size, 2);
  assert.equal(t.opacity, 1);
});

test('a shape does not inherit the pen width either', () => {
  const t = new Tools();
  t.set('pen'); t.setSize(6);
  t.set('rect');
  assert.equal(t.size, 2);
});

test('setting a width touches only the current tool', () => {
  const t = new Tools();
  t.set('highlighter'); t.setSize(28);
  t.set('pen');
  assert.equal(t.size, 2);
  t.set('highlighter');
  assert.equal(t.size, 28);
});

test('opacity is a property of the tool, not a setting', () => {
  const t = new Tools();
  assert.equal(t.opacity, 1);
  t.set('highlighter');
  assert.equal(t.opacity, 0.35);
});

test('the widths offered suit the tool', () => {
  const t = new Tools();
  t.set('pen');
  assert.ok(Math.max(...t.widths) <= 8, 'a pen has no use for 28pt');
  t.set('highlighter');
  assert.ok(Math.min(...t.widths) >= 8, 'a highlighter has no use for 1pt');
});

test('an unknown tool is ignored rather than breaking the toolbar', () => {
  const t = new Tools();
  t.set('nonsense');
  assert.equal(t.mode, 'pen');
});

test('colour is shared across tools, as a reader expects', () => {
  const t = new Tools();
  t.setColor('#dc2626');
  t.set('rect');
  assert.equal(t.color, '#dc2626');
});

/**
 * The ink layers' touch-action chain.
 *
 * This lives in a test because the failure is silent: the CSS is valid, the
 * JS is right, nothing errors, and the only symptom is that a reader's finger
 * stops scrolling — on a tablet none of us is holding. It shipped once
 * exactly that way (task #683).
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const CSS = readFileSync(
  new URL('../../parody_web_annotate/static/parody_web_annotate/css/annotate.css',
          import.meta.url), 'utf8');

/** Declarations of `prop` whose selector mentions `needle`, comments stripped. */
function rulesFor(needle, prop) {
  const bare = CSS.replace(/\/\*[\s\S]*?\*\//g, '');
  return [...bare.matchAll(/([^{}]+)\{([^}]*)\}/g)]
    .filter(([, selector]) => selector.includes(needle))
    .flatMap(([, , body]) => body.split(';')
      .map((d) => d.trim())
      .filter((d) => d.startsWith(`${prop}:`))
      .map((d) => d.slice(prop.length + 1).trim()));
}

test('the canvas takes its touch-action from the host, and never sets its own', () => {
  // touch-action is decided on the element the finger HITS. The host can say
  // what it likes; if the canvas declares its own value, the host is mute.
  const declared = rulesFor('canvas', 'touch-action');
  assert.ok(declared.length > 0, 'the canvas chain is declared at all');
  assert.deepEqual([...new Set(declared)], ['inherit'],
                   'an ink canvas may only inherit');
});

test('Konva\'s own div is in the chain too', () => {
  // Konva inserts .konvajs-content between the host and the canvas. Miss it
  // and the canvas inherits `auto` from THAT div instead of the host's value
  // — which reads as fixed in the stylus case and is wrong in the other.
  const inherits = (sel) => rulesFor(sel, 'touch-action').includes('inherit');
  assert.ok(inherits('.ink-layer .konvajs-content'), 'page layer');
  assert.ok(inherits('.ink-pad .konvajs-content'), 'scratch pad');
});

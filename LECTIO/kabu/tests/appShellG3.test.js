// App shell: the menu's focus trap and the loader. (The legal reader went with its menu links.)
// hands focus back to its opener and the open menu takes Tab back, and the boot
// loader draws the header's lettering instead of a monospace wordmark.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');
test('the open menu pulls stray focus back into the menu', () => {
  const source = read('src/components/UnderlayNav.jsx');
  const trap = source.slice(source.indexOf('} else if (e.key === "Tab" && isOpen) {'), source.indexOf('document.addEventListener("keydown", onKeydown);'));
  assert.match(trap, /if \(!items\.includes\(document\.activeElement\)\) \{\s*e\.preventDefault\(\);\s*\(e\.shiftKey \? last : first\)\.focus\(\);/);
  // there is no legal reader any more: nothing else owns Tab while the menu is open
  assert.doesNotMatch(source, /LegalDoc|\.legal\[/);
});

test('the loader draws the header wordmark (EUROPA in the header lettering); track, bar and label stay', () => {
  const source = read('src/components/IndagoLoader.jsx');
  assert.match(source, /import \{ letteringWord \} from "\.\/indagoLettering\.js";/);
  assert.match(source, /const WORDMARK = letteringWord\("Europa"\);/);
  assert.match(source, /<svg className="ndg-loader-word" viewBox=\{WORDMARK\.viewBox\}/);
  assert.doesNotMatch(source, /SF Mono|ndg-loader-beta/);
  for (const part of ['ndg-loader-track', 'ndg-loader-bar', 'ndg-loader-label', 'ndgSweep']) assert.ok(source.includes(part), part);
});

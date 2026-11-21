import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { armedItem, paletteStep } from '../src/lib/paletteConfirm.js';

const paid = { id: 'gen-7203', confirm: true, go: () => '/GenerateReport?ticker=7203' };
const plain = { id: 'm-home', go: () => '/Home' };

test('a paid item arms on the first activation and runs on the second', () => {
  assert.equal(paletteStep(paid, null), 'arm');
  assert.equal(paletteStep(paid, 'gen-7203'), 'run');
  assert.equal(paletteStep(paid, 'gen-6758'), 'arm', 'another armed row does not confirm this one');
});

test('ordinary items run at once and nothing runs for an empty list', () => {
  assert.equal(paletteStep(plain, null), 'run');
  assert.equal(paletteStep(plain, 'gen-7203'), 'run');
  assert.equal(paletteStep(undefined, null), 'none');
});

test('armed item disappears when the list no longer has it', () => {
  assert.equal(armedItem([paid, plain], 'gen-7203'), paid);
  assert.equal(armedItem([plain], 'gen-7203'), null);
  assert.equal(armedItem([paid], null), null);
  assert.equal(armedItem([{ id: 'gen-7203' }], 'gen-7203'), null, 'only confirm items can be armed');
});

test('the palette wires the confirm step: ticker rows are marked, never navigate on the first Enter, never window.confirm', () => {
  const src = readFileSync(new URL('../src/components/CommandPalette.jsx', import.meta.url), 'utf8');
  assert.match(src, /sub: `\$\{listed\.name\} · Report mode`, confirm: true,/);
  assert.match(src, /paletteStep\(it, armedId\)/);
  assert.match(src, /if \(step === "arm"\) \{ setArmedId\(it\.id\); return; \}/);
  assert.match(src, />Generate report</);
  assert.doesNotMatch(src, /window\.confirm|\bconfirm\(/);
  // The arm state resets when the query changes, when the list is reopened, and when the highlight moves.
  assert.match(src, /setQ\(e\.target\.value\); setActive\(0\); setArmedId\(null\)/);
  assert.match(src, /setQ\(""\); setActive\(0\); setArmedId\(null\)/);
});

// k4-h1: the Reports (#/Reports → Home.jsx), Activist and API pages each carry
// exactly one page-level <h1> naming the page, without changing the visual
// design (Reports/Activist promote their existing visible title; API adds a
// visually-hidden h1 because its visible title is the gate dialog's h2).
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const src = p => readFileSync(new URL(`../src/${p}`, import.meta.url), 'utf8');
const count = (s, re) => (s.match(re) || []).length;

test('Reports page: the visible "Research" title is the h1', () => {
  const s = src('pages/Home.jsx');
  assert.equal(count(s, /as="h1"|<h1[\s>]/g), 1);
  assert.match(s, /as="h1"[\s\S]{0,600}?>\s*Research\s*<\/MorphItem>/);
  assert.doesNotMatch(s, /as="h2"[\s\S]{0,600}?>\s*Research\s*</);
});


// Wave A8: three.js (voice mode) and the full company list no longer ride in the
// Query and Reports page chunks; each loads on first use.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { POPULAR_COMPANIES, buildCompanyIndex, matchCompanyIndex } from '../src/lib/companyIndex.js';

const src = (p) => readFileSync(new URL(`../src/${p}`, import.meta.url), 'utf8');

test('the search box loads the company list on first use; Popular renders without it', () => {
  const bar = src('components/home/SearchBar.jsx');
  assert.doesNotMatch(bar, /companies\.json/, 'no static import of the 226 KB list');
  assert.match(bar, /onFocus=\{\(\) => \{ setIsFocused\(true\); wantIndex\(\); \}\}/);
  assert.match(bar, /onChange=\{\(e\) => \{ setQuery\(e\.target\.value\); setError\(null\); wantIndex\(\); \}\}/);
  assert.match(src('lib/companyIndex.js'), /import\("@\/data\/companies\.json"\)/);
});

test('the inline Popular companies are exactly the rows in companies.json', () => {
  const companies = JSON.parse(src('data/companies.json'));
  const index = buildCompanyIndex(companies);
  assert.equal(POPULAR_COMPANIES.length, 20);
  for (const popular of POPULAR_COMPANIES) {
    const row = index.find((c) => c.tickerLower === popular.tickerLower);
    assert.ok(row, popular.ticker);
    assert.equal(popular.name, row.name, popular.ticker);
    assert.equal(popular.nameLower, row.nameLower);
    assert.equal(popular.name_jp, row.name_jp, popular.ticker);
    assert.deepEqual(popular.aka, row.aka, popular.ticker);
    assert.equal(popular.s, row.s, popular.ticker);
  }
  assert.deepEqual(index.slice(0, 3).map((c) => c.ticker), [...index].sort((a, b) => a.tickerLower.localeCompare(b.tickerLower)).slice(0, 3).map((c) => c.ticker));
});

test('Enter before the company list arrives: one submit, the top match as the dropdown would pick, no false "No results"', () => {
  const bar = src('components/home/SearchBar.jsx');
  assert.match(bar, /if \(waitingForIndex\.current \|\| isSubmitting\) return;/, 'a second Enter while waiting is ignored');
  assert.match(bar, /index = await loadCompanyIndex\(\)\.catch\(\(\) => POPULAR_COMPANIES\);/);
  assert.match(bar, /const pick = pickSubmission\(text, index, highlight, recentCompanies\);/, 'after the wait, the pick is made as the dropdown would');
  assert.match(bar, /\(\) => dropdownRows\(query, companyIndex, recentCompanies\)/, 'the dropdown and Enter share one row list');
  assert.match(bar, /const matches = matchCompanies\(index, q\);/, 'and one matcher');
  assert.match(bar, /\{query && !companyIndex && \(/);
  assert.match(bar, /Loading companies…/);
  assert.match(bar, /\{query && companyIndex && filteredCompanies\.length === 0 && \(/);
  // The matcher itself.
  const fn = bar.slice(bar.indexOf('function matchCompanies('), bar.indexOf('\n}\n', bar.indexOf('function matchCompanies(')) + 2);
  const matchCompanies = new Function('MAX_RESULTS', 'matchCompanyIndex', `${fn}; return matchCompanies;`)(20, matchCompanyIndex);
  const index = buildCompanyIndex([{ ticker: 'AAPL', name: 'Apple Inc.' }, { ticker: 'MSFT', name: 'Microsoft Corporation' }]);
  assert.equal(matchCompanies(index, 'apple')[0].ticker, 'AAPL');
  assert.equal(matchCompanies(index, 'ms')[0].ticker, 'MSFT');
  assert.equal(matchCompanies(index, 'aapl')[0].ticker, 'AAPL');
  assert.deepEqual(matchCompanies(null, 'apple'), []);
});

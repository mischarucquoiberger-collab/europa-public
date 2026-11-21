// USA: the Reports search and the ⌘K palette work on US listed companies. A US
// symbol is 1 to 5 letters with an optional class suffix (BRK.B, BF-B), typed in
// any case and sent in capitals. An ordinary word ("home", "apple") is shaped
// like a symbol too, so typed text counts as a ticker only when the loaded
// index has that symbol. Run over the real companies.json the search box loads.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  POPULAR_COMPANIES, US_TICKER_RE, buildCompanyIndex, findIndexedTicker, matchCompanyIndex,
  normalizeCompanyText, normalizeUsTicker,
} from '../src/lib/companyIndex.js';

const src = (p) => readFileSync(new URL(`../src/${p}`, import.meta.url), 'utf8');
const rows = JSON.parse(src('data/companies.json'));
const index = buildCompanyIndex(rows);
const tickers = (q, n = 5) => matchCompanyIndex(index, q.trim().toLowerCase(), n).map((c) => c.ticker);
const top = (q) => tickers(q)[0];

test('the built-in list is US listed companies only, with US-shaped unique symbols', () => {
  assert.equal(rows.length, 47);
  const symbols = rows.map((r) => r.ticker);
  assert.equal(new Set(symbols).size, symbols.length, 'no duplicate symbols');
  for (const r of rows) {
    assert.match(r.ticker, US_TICKER_RE, r.ticker);
    assert.equal(r.ticker, r.ticker.toUpperCase(), r.ticker);
    assert.ok(typeof r.name === 'string' && r.name.length > 1, r.ticker);
    assert.equal(r.name_jp, undefined, `${r.ticker} carries no Japanese name`);
    assert.doesNotMatch(JSON.stringify(r), /[぀-ヿ一-鿿]|Japan|Tokyo|TSE|TOPIX/, r.ticker);
  }
  const byTicker = Object.fromEntries(rows.map((r) => [r.ticker, r.name]));
  assert.equal(byTicker.AAPL, 'Apple Inc.');
  assert.equal(byTicker.MSFT, 'Microsoft Corporation');
  assert.equal(byTicker.NVDA, 'NVIDIA Corporation');
  assert.equal(byTicker['BRK.B'], 'Berkshire Hathaway Inc.');
  assert.equal(byTicker.JPM, 'JPMorgan Chase & Co.');
  assert.equal(byTicker.DUOL, 'Duolingo, Inc.');
  assert.equal(byTicker.ELF, 'e.l.f. Beauty, Inc.');
  assert.equal(byTicker.PLNT, 'Planet Fitness, Inc.');
  assert.equal(byTicker.HD, undefined, 'no company whose name would make "home" a match');
  assert.ok(!rows.some((r) => /home|report/i.test(r.name)), 'typing "home" or "reports" matches no company');
});

test('every rotating placeholder company is in the built-in list (the search finds it)', () => {
  const bar = src('components/home/SearchBar.jsx');
  const phrases = bar.slice(bar.indexOf('const HOME_PLACEHOLDER_PHRASES = ['), bar.indexOf('];', bar.indexOf('const HOME_PLACEHOLDER_PHRASES = [')));
  const listed = [...phrases.matchAll(/"([A-Z][A-Z.-]{0,6})\s{3}([^"]+)"/g)];
  assert.ok(listed.length >= 8, `${listed.length} symbol placeholders`);
  assert.equal(listed[0][1], 'NVDA', 'NVDA is the first company placeholder');
  for (const [, symbol, name] of listed) {
    const row = index.find((c) => c.ticker === symbol);
    assert.ok(row, symbol);
    assert.equal(row.name, name, symbol);
    assert.equal(top(symbol.toLowerCase()), symbol);
  }
  for (const [, name] of phrases.matchAll(/"Try ([^"…]+)…"/g)) assert.ok(tickers(name).length > 0, name);
  assert.doesNotMatch(phrases, /Japanese|[぀-ヿ一-鿿]|\d{4}/);
});

test('US symbol shape: 1 to 5 letters, optional .X / -X class suffix, any case, shown in capitals', () => {
  for (const ok of ['A', 'V', 'KO', 'AAPL', 'GOOGL', 'BRK.B', 'BRK.A', 'BF-B', 'brk.b', 'aapl', ' msft ']) {
    assert.notEqual(normalizeUsTicker(ok), '', ok);
  }
  assert.equal(normalizeUsTicker('aapl'), 'AAPL');
  assert.equal(normalizeUsTicker(' brk.b '), 'BRK.B');
  assert.equal(normalizeUsTicker('bf-b'), 'BF-B');
  for (const bad of ['', ' ', 'ABCDEF', 'AAPL1', '7203', '7203.T', 'BRK.BB', 'BRK..B', '.B', 'BRK.', 'AA PL', 'AAPL!', 'ＡＡＰＬ', 'トヨタ']) {
    assert.equal(normalizeUsTicker(bad), '', JSON.stringify(bad));
  }
});

test('an ordinary word is not a ticker unless the index has that symbol', () => {
  for (const word of ['home', 'apple', 'reports', 'deep', 'micro', 'zzzz']) {
    assert.equal(findIndexedTicker(index, word), null, word);
  }
  assert.equal(findIndexedTicker(index, 'aapl')?.ticker, 'AAPL');
  assert.equal(findIndexedTicker(index, 'NvDa')?.ticker, 'NVDA');
  assert.equal(findIndexedTicker(index, 'v')?.ticker, 'V');
  assert.equal(findIndexedTicker(index, 'brk.b')?.ticker, 'BRK.B');
  assert.equal(findIndexedTicker(index, 'BRK-B')?.ticker, 'BRK.B', 'either class separator');
  assert.equal(findIndexedTicker(index, 'BRK.A'), null, 'a class the list does not have');
  assert.equal(findIndexedTicker(index, 'aapl1'), null);
  assert.equal(findIndexedTicker(null, 'aapl'), null);
  // A list sent later (e.g. by a backend) decides what counts.
  const later = buildCompanyIndex([{ ticker: 'HOME', name: 'Example Home Co.' }]);
  assert.equal(findIndexedTicker(later, 'home')?.ticker, 'HOME');
  assert.equal(findIndexedTicker(later, 'aapl'), null);
});

test('search by name and by symbol on the built-in list', () => {
  assert.equal(top('apple'), 'AAPL');
  assert.equal(top('Apple Inc.'), 'AAPL');
  assert.equal(top('aapl'), 'AAPL');
  assert.equal(top('AAPL'), 'AAPL');
  assert.equal(top('micro'), 'MSFT');
  assert.ok(tickers('micro').includes('AMD'), 'Advanced Micro Devices also matches');
  assert.equal(top('brk.b'), 'BRK.B');
  assert.equal(top('BRK-B'), 'BRK.B');
  assert.equal(top('berkshire'), 'BRK.B');
  assert.equal(top('v'), 'V', 'an exact one-letter symbol ranks first');
  assert.equal(top('ko'), 'KO');
  assert.equal(top('coca-cola'), 'KO');
  assert.equal(top('google'), 'GOOGL', 'other names (aka) are searched');
  assert.equal(top('facebook'), 'META');
  assert.equal(top('nvidia'), 'NVDA');
  assert.equal(top('duolingo'), 'DUOL');
  assert.equal(top('shake shack'), 'SHAK');
  assert.equal(top('crocs'), 'CROX');
  assert.equal(top('e.l.f.'), 'ELF');
  assert.equal(top('procter & gamble'), 'PG');
  assert.equal(top('johnson johnson'), 'JNJ', "found without the '&'");
});

test("a symbol followed by its company's name (the placeholder's own format) finds that company", () => {
  assert.deepEqual(tickers('AAPL   Apple Inc.'), ['AAPL']);
  assert.deepEqual(tickers('nvda nvidia'), ['NVDA']);
  assert.deepEqual(tickers('BRK.B Berkshire'), ['BRK.B']);
  assert.deepEqual(tickers('duol, duolingo'), ['DUOL']);
});

test('no false matches', () => {
  assert.deepEqual(matchCompanyIndex(index, 'home'), []);
  assert.deepEqual(matchCompanyIndex(index, 'reports'), []);
  assert.deepEqual(matchCompanyIndex(index, 'toyota'), []);
  assert.deepEqual(matchCompanyIndex(index, ''), []);
  assert.deepEqual(matchCompanyIndex(index, '&'), [], "a lone '&' matches nothing");
  assert.deepEqual(matchCompanyIndex(null, 'apple'), []);
  assert.deepEqual(matchCompanyIndex(index, 'zzzzqqqq'), []);
  assert.ok(matchCompanyIndex(index, 'a').length <= 20);
});

test('normalisation', () => {
  assert.equal(normalizeCompanyText('The Coca-Cola Company'), 'thecocacolacompany');
  assert.equal(normalizeCompanyText('Ｐ＆Ｇ'), 'p&g', 'full-width letters and ampersand');
  assert.equal(normalizeCompanyText("McDonald's"), 'mcdonalds');
});

test('the inline Popular companies are US rows of the built-in list', () => {
  assert.equal(POPULAR_COMPANIES[0].ticker, 'AAPL');
  for (const c of POPULAR_COMPANIES) assert.match(c.ticker, US_TICKER_RE, c.ticker);
});

test('the palette offers company matches by name or symbol, confirmed before a report starts', () => {
  const palette = src('components/CommandPalette.jsx');
  assert.match(palette, /matchCompanyIndex\(companyIndex, query\.toLowerCase\(\), 5\)/);
  assert.match(palette, /findIndexedTicker\(companyIndex \|\| POPULAR_COMPANIES, query\)/);
  assert.match(palette, /id: "co-" \+ c\.ticker/);
  assert.match(palette, /confirm: true, go: \(\) => `\/GenerateReport\?ticker=\$\{encodeURIComponent\(c\.ticker\)\}`/);
  assert.match(palette, /loadCompanyIndex\(\)/);
  assert.match(palette, /placeholder="Jump to a page, a company or a ticker \(AAPL\)…"/);
  assert.match(palette, /No matches — try a page name or a US ticker\./);
  assert.doesNotMatch(palette, /TSE|JPX|7203|Japanese/);
});

test('the search box: US messages; free text is a listed company or a US-shaped ticker', () => {
  const bar = src('components/home/SearchBar.jsx');
  assert.match(bar, /setError\("Enter a valid ticker symbol \(e\.g\. AAPL\)"\);/);
  assert.match(bar, /setError\("Select a listed company or enter a valid US ticker\."\);/);
  assert.match(bar, /const listed = findIndexedTicker\(index, trimmed\.split\(\/\[\\s,\]\+\/\)\[0\]\);/);
  assert.match(bar, /const symbol = normalizeUsTicker\(trimmed\);\n\s+return symbol \? \{ ticker: symbol, name: "" \} : null;/);
  assert.match(bar, /return normalizeUsTicker\(/);
  assert.doesNotMatch(bar, /TSE|7974|Search in Japanese|トヨタ/);
});

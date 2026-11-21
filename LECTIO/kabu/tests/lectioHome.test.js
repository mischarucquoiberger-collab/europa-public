import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { build } from 'esbuild';

const require = createRequire(import.meta.url);
const root = fileURLToPath(new URL('../', import.meta.url));
const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');
const source = read('src/pages/LectioHome.jsx');
const css = read('src/index.css');

// The icons are not under test (and lucide-react's CommonJS build will not load here).
const iconStub = { name: 'icon-stub', setup(b) {
  b.onResolve({ filter: /^lucide-react$/ }, () => ({ path: 'lucide-react', namespace: 'icon-stub' }));
  b.onLoad({ filter: /.*/, namespace: 'icon-stub' }, () => ({ contents: 'export const Search = () => null;', loader: 'js' }));
} };

async function load(entry) {
  const out = await build({ entryPoints: [root + entry], bundle: true, write: false, platform: 'node',
    format: 'cjs', jsx: 'automatic', external: ['react', 'react/*', 'react-dom', 'react-dom/*'],
    alias: { '@': root + 'src' }, logLevel: 'silent', plugins: [iconStub] });
  const module = { exports: {} };
  new Function('require', 'module', 'exports', out.outputFiles[0].text)(require, module, module.exports);
  return module.exports;
}
const home = await load('src/pages/LectioHome.jsx');

// index.html's pre-paint rule, to check that it skips the splash for exactly the deep links Home opens.
const prePaint = read('index.html').match(/<script>([\s\S]*?)<\/script>/)[1];
function splashOnLoad(hash) {
  let enabled;
  new Function('location', 'document', prePaint)({ hash }, { documentElement: { classList: { toggle: (_, v) => { enabled = v; } } } });
  return enabled;
}

test('Home embeds the local Europa markets page', () => {
  const html = renderToStaticMarkup(React.createElement(home.default));
  assert.match(html, /<iframe[^>]+title="Europa markets"/);
  assert.ok(html.includes('src="http://127.0.0.1:3015"'));
  // While the desk has not answered: a quiet loading line, not the "not running" message.
  assert.match(html, /role="status"[^>]*><p>Loading the markets desk…<\/p>/);
  assert.doesNotMatch(html, /not running/);
});

const GOOD = [
  ['#/Home?page=%2Fstocks%2FNVDA', '/stocks/NVDA'],
  ['#/Home?page=/stocks/NVDA', '/stocks/NVDA'],
  ['#/Home?page=%2Fstocks%2FBRK.B', '/stocks/BRK.B'],
  ['#/Home?page=%2Fstocks%2FI%3ASPX', '/stocks/I:SPX'],
  ['#/Home?page=%2Freports', '/reports'],
  ['#/Home?page=%2Freports%3Fticker%3DAAPL', '/reports?ticker=AAPL'],
];
const HOSTILE = [
  '#/Home', '#/Home?page=', '#/Home?page=%2F%2Fevil.example', '#/Home?page=//evil.example',
  '#/Home?page=%2Fstocks%2F..%2F..%2Fx', '#/Home?page=/stocks/../../x', '#/Home?page=%2Fstocks%2F..',
  '#/Home?page=%2Fstocks%2F%252e%252e', '#/Home?page=%2Fstocks%2FNVDA%2F..%2F..%2Fx',
  '#/Home?page=https%3A%2F%2Fevil.example%2Fstocks%2FX', '#/Home?page=javascript%3Aalert(1)',
  '#/Home?page=%2Freportsx', '#/Home?page=%2Fapi%2Fsecret', '#/Home?page=%2F', '#/Home?page=%5C%5Cevil.example',
];

test('page= opens only a ticker page or the reports page of the desk', () => {
  for (const [hash, path] of GOOD) assert.equal(home.deskPage(hash), path, hash);
  for (const hash of HOSTILE) assert.equal(home.deskPage(hash), '', hash);
  // The frame's address can only ever be the desk's own origin plus one of those paths.
  assert.match(source, /const src = MARKETS_URL \+ marketPath;/);
  assert.match(source, /setMarketPath\(deskPage\(window\.location\.hash\)\)/);
});

test('index.html skips the splash for exactly the deep links Home opens', () => {
  for (const [hash] of GOOD) assert.equal(splashOnLoad(hash), false, hash);
  for (const hash of HOSTILE) assert.equal(splashOnLoad(hash), true, hash);
});

test('the height listener accepts only the desk frame at the desk origin', () => {
  assert.match(source, /if \(!marketOrigin \|\| event\.origin !== marketOrigin \|\| event\.source !== frame\.current\?\.contentWindow\) return;/);
  assert.match(source, /event\.data\?\.type !== "europa-market-height" \|\| !Number\.isFinite\(event\.data\.height\)/);
  // A zero height would park the frame where the browser stops rendering it.
  assert.match(source, /setHeight\(Math\.max\(MIN_FRAME, Math\.ceil\(event\.data\.height\)\)\)/);
});

test('when the desk does not answer, Home says so, says how to start it and offers Retry', () => {
  assert.ok(home.DESK_ANSWER_MS >= 2000 && home.DESK_ANSWER_MS <= 6000, 'a few seconds after the frame loads');
  assert.ok(home.DESK_LOAD_MS > home.DESK_ANSWER_MS && home.DESK_LOAD_MS <= 30000, 'or when the load never comes');
  assert.match(source, /const onFrameLoad = \(\) => \{ if \(!heard\.current\) giveUpAfter\(DESK_ANSWER_MS\); \};/);
  assert.match(source, /giveUpAfter\(DESK_LOAD_MS\);/);
  assert.match(source, /<p className="desk-status__title">The markets desk is not running\.<\/p>/);
  assert.match(source, /In the markets folder: <code>npm run dev<\/code>/);
  assert.match(source, /<button type="button" className="desk-status__retry" onClick=\{retryNow\}>Retry<\/button>/);
  // Retry remounts the frame; the message goes as soon as the desk reports a height.
  assert.match(source, /<iframe key=\{attempt\}/);
  assert.match(source, /heard\.current = true;\s*window\.clearTimeout\(watchdog\.current\);\s*setHeight\([^;]+;\s*setStatus\("ready"\);/);
});

test('the top blur band: fixed over the header, driven by --home-logo-backdrop, blur with a fallback, never takes clicks', () => {
  const band = css.match(/\.home-top-blur \{([^}]*)\}/)[1];
  assert.match(band, /position:fixed; top:0; left:0; right:0; height:84px; z-index:50;/);
  assert.match(band, /pointer-events:none;/);
  assert.match(band, /opacity:var\(--home-logo-backdrop, 0\);/);
  assert.match(band, /border-bottom:1px solid rgba\(255, 255, 255, 0\.08\);/);
  assert.match(band, /background:rgba\(14, 20, 32, 0\.94\);/, 'the ground where backdrop-filter is not supported');
  assert.doesNotMatch(band, /box-shadow|gradient|backdrop-filter/);
  const supported = css.match(/@supports \(\(-webkit-backdrop-filter: blur\(1px\)\) or \(backdrop-filter: blur\(1px\)\)\) \{\s*\.home-top-blur \{([^}]*)\}/)[1];
  assert.match(supported, /background:rgba\(14, 20, 32, 0\.72\);/);
  assert.match(supported, /-webkit-backdrop-filter:blur\(14px\) saturate\(1\.15\);/);
  assert.match(supported, /\sbackdrop-filter:blur\(14px\) saturate\(1\.15\);/);
  assert.match(css, /body:is\(\[data-menu-status="open"\], \[data-menu-status="closing"\]\) \.home-top-blur \{ visibility:hidden; \}/);
  // Only Home mounts it, into <body> (outside the sliding page); the variable is set by a passive
  // scroll handler over the first 84 px and removed when Home is left.
  assert.match(source, /createPortal\(<div className="home-top-blur" aria-hidden="true" \/>, document\.body\)/);
  assert.match(source, /Math\.min\(1, Math\.max\(0, window\.scrollY \/ HEADER_SPACE\)\)/);
  assert.match(source, /const HEADER_SPACE = 84;/);
  assert.match(source, /window\.addEventListener\("scroll", updateBackdrop, \{ passive: true \}\);/);
  assert.match(source, /b\.style\.removeProperty\("--home-logo-backdrop"\);/);
});

test('the stock finder: ranked matches with names, ticker-shaped text, nothing for nonsense', async () => {
  const finder = await load('src/components/StockFinder.jsx');
  const nvda = finder.findStocks('nvda');
  assert.equal(nvda[0].ticker, 'NVDA');
  assert.ok(nvda[0].name.length > 0 && nvda[0].name !== 'NVDA');
  assert.equal(finder.findStocks('apple')[0].ticker, 'AAPL');
  assert.equal(finder.findStocks('  brk.b ')[0].ticker, 'BRK.B');
  assert.deepEqual(finder.findStocks('XYZQ'), [{ ticker: 'XYZQ', name: 'Open the XYZQ chart' }]);
  for (const nonsense of ['', '   ', '!!!', 'hello world', 'zzzzzzzzzz', '<script>', '../x', '//evil.example']) {
    assert.deepEqual(finder.findStocks(nonsense), [], JSON.stringify(nonsense));
  }
  assert.ok(finder.findStocks('a').length <= 6);
  // The new tab lands on the stock page through a deep link that Home accepts and the splash skips.
  const href = finder.stockHref('I:SPX');
  assert.equal(home.deskPage(href), '/stocks/I:SPX');
  assert.equal(splashOnLoad(href), false);
});

test('the stock finder finds the nav container even when it renders later or again', () => {
  const finder = read('src/components/StockFinder.jsx');
  assert.match(finder, /new MutationObserver\(find\)/);
  assert.match(finder, /if \(current\?\.isConnected\) return;/);
  assert.match(finder, /onKeyDown=\{\(e\) => \{ if \(e\.key === "Escape"\) \{ e\.preventDefault\(\); close\(\{ refocus: true \}\); \} \}\}/);
  assert.match(finder, /role="combobox"/);
  assert.match(finder, /aria-activedescendant=/);
});

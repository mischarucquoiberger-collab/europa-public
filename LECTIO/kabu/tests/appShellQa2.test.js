// App shell QA round 2: Back to Home returns to the same spot, the legal reader
// keeps Tab and closes on navigation, the menu reopens at its top, tab titles
// match routes case-insensitively, canonical product names, a branded 404, an
// idle Generate Report without a company, and Home's phone details.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';

const require = createRequire(import.meta.url);
const root = fileURLToPath(new URL('../', import.meta.url));
const read = (p) => readFileSync(new URL(`../${p}`, import.meta.url), 'utf8');

async function bundle(stubs, contents) {
  const output = await build({
    stdin: { contents, resolveDir: root, loader: 'jsx' },
    bundle: true, write: false, platform: 'node', format: 'cjs', jsx: 'automatic', loader: { '.css': 'empty' },
    external: ['react', 'react/*', 'react-dom', 'react-dom/*', 'react-router-dom'], logLevel: 'silent',
    plugins: [{ name: 'stubs', setup(builder) {
      builder.onResolve({ filter: /.*/ }, (args) => (args.path in stubs ? { path: args.path, namespace: 'stub' } : undefined));
      builder.onLoad({ filter: /.*/, namespace: 'stub' }, (args) => ({ contents: stubs[args.path], loader: 'js' }));
    } }],
  });
  const module = { exports: {} };
  new Function('require', 'module', 'exports', output.outputFiles[0].text)(require, module, module.exports);
  return module.exports;
}

const nothing = 'export default function Stub(){return null;}';
const { restoreScrollWhenLaidOut } = await bundle({
  '@/lib/AuthContext': 'export const useAuth=()=>({});',
  '@/components/UnderlayNav': nothing,
  '@/components/CommandPalette': nothing,
  '@/components/KeyboardShortcuts': nothing,
  '@/lib/useIsPhone': 'export default ()=>false;',
  '@/components/MobileGate': nothing,
}, 'export { restoreScrollWhenLaidOut } from "./src/Layout.jsx";');

/* A window whose page grows as sections load: scrollTo clamps to the page height. */
function fakeWindow() {
  const listeners = new Map();
  const timers = new Map();
  let nextTimer = 1;
  let observer = null;
  const win = {
    scrollY: 0,
    pageHeight: 900,
    viewport: 700,
    document: { documentElement: { style: { overflowAnchor: '' } }, body: {} },
    scrollTo(_x, y) { win.scrollY = Math.max(0, Math.min(y, win.pageHeight - win.viewport)); },
    addEventListener(type, fn) { listeners.set(type, fn); },
    removeEventListener(type, fn) { if (listeners.get(type) === fn) listeners.delete(type); },
    setTimeout(fn, ms) { const id = nextTimer++; timers.set(id, { fn, ms }); return id; },
    clearTimeout(id) { timers.delete(id); },
    setInterval() { return 0; },
    clearInterval() {},
    ResizeObserver: class { constructor(cb) { observer = cb; } observe() {} disconnect() { observer = null; } },
  };
  return {
    win, listeners, timers,
    grow(height) { win.pageHeight = height; observer?.(); },
    fire(ms) { for (const [id, t] of [...timers]) if (t.ms === ms) { timers.delete(id); t.fn(); } },
  };
}

test('Back to Home: the saved offset is re-applied as the page grows, with scroll anchoring off', () => {
  const h = fakeWindow();
  restoreScrollWhenLaidOut(4228, { win: h.win, timeoutMs: 6000, settleMs: 700 });
  assert.equal(h.win.document.documentElement.style.overflowAnchor, 'none');
  assert.equal(h.win.scrollY, 200, 'first paint is short: the offset clamps');
  h.grow(3000);
  assert.equal(h.win.scrollY, 2300);
  h.grow(6000);
  assert.equal(h.win.scrollY, 4228, 'reached once the sections have laid out');
  h.fire(700);                                   // held still: done
  assert.equal(h.win.document.documentElement.style.overflowAnchor, '', 'anchoring restored');
  assert.equal(h.listeners.size, 0);
  h.win.scrollY = 10;
  h.grow(7000);
  assert.equal(h.win.scrollY, 10, 'no longer follows the page after it settled');
});

test('Back to Home: the reader scrolling or a key press ends the restore at once', () => {
  for (const event of ['wheel', 'touchstart', 'keydown', 'mousedown']) {
    const h = fakeWindow();
    restoreScrollWhenLaidOut(4000, { win: h.win });
    h.listeners.get(event)();
    h.win.scrollY = 50;
    h.grow(8000);
    assert.equal(h.win.scrollY, 50, event);
    assert.equal(h.win.document.documentElement.style.overflowAnchor, '');
  }
});

test('Back to Home: a page that never grows tall enough stops at the deadline; cancel is idempotent', () => {
  const h = fakeWindow();
  const cancel = restoreScrollWhenLaidOut(9000, { win: h.win, timeoutMs: 6000 });
  h.fire(6000);
  assert.equal(h.win.document.documentElement.style.overflowAnchor, '');
  cancel();
  cancel();
  assert.equal(h.listeners.size, 0);
});

test('Layout saves the offset on leaving a page and restores it on the return shape only', () => {
  const layout = read('src/Layout.jsx');
  assert.match(layout, /window\.history\.scrollRestoration = "manual"/);
  assert.match(layout, /if \(leaving && leaving !== location\.pathname\) saveScroll\(leaving, lastScrollRef\.current\);/);
  assert.match(layout, /if \(target > 0\) restoreRef\.current = restoreScrollWhenLaidOut\(target\);/);
  assert.match(layout, /React\.useLayoutEffect\(\(\) => \{\s*const stack = pathStackRef\.current;/);
});

test('NavigationTracker: route titles match case-insensitively, with canonical product names', async () => {
  const { routeTitle } = await bundle({}, 'export { routeTitle } from "./src/lib/NavigationTracker.jsx";');
  assert.equal(routeTitle('/home'), 'Home');
  assert.equal(routeTitle('/REPORTS'), 'Research Reports');
  assert.equal(routeTitle('/deepresearch'), 'Callisto');
  assert.equal(routeTitle('/Viewer'), 'Report Viewer');
  assert.equal(routeTitle('/Account'), null, 'no account pages');
  assert.equal(routeTitle('/nope'), null);
  assert.equal(routeTitle(undefined), null);
  const gate = read('src/components/MobileGate.jsx');
  assert.match(gate, /Reports: "Research Reports",/);
  assert.match(gate, />Home<\/Link>/);
  for (const source of [gate, read('src/lib/NavigationTracker.jsx')]) {
    assert.doesNotMatch(source, /News Scanner|Activist|Screener|Research Query|Market Home|Market summary|Sign in|Account/);
  }
});

test('404: Indago styling, sentence case, decoded and wrapped path, its own tab title', async () => {
  const { shownPath, NOT_FOUND_TITLE } = await bundle({}, 'export { shownPath, NOT_FOUND_TITLE } from "./src/lib/PageNotFound.jsx";');
  assert.equal(NOT_FOUND_TITLE, 'Page not found · Europa');
  assert.equal(shownPath('/%E6%A0%AA%E5%BC%8F'), '株式');
  assert.equal(shownPath('/bad%E0%A4%A'), 'bad%E0%A4%A', 'a malformed escape is shown as typed');
  const long = shownPath('/' + 'x'.repeat(500));
  assert.equal(long.length, 120);
  assert.ok(long.endsWith('…'));
  // cut by code point: an emoji at the cut is never split into a lone surrogate
  const emoji = shownPath('/' + 'x'.repeat(118) + '😀😀');
  assert.equal(emoji, 'x'.repeat(118) + '😀😀', 'exactly 120 code points: shown whole');
  const cut = shownPath('/' + 'x'.repeat(118) + '😀😀😀');
  assert.equal(cut, 'x'.repeat(118) + '😀…');
  assert.doesNotMatch(cut, /[\uD800-\uDBFF](?![\uDC00-\uDFFF])/);
  const page = read('src/lib/PageNotFound.jsx');
  assert.match(page, /\[overflow-wrap:anywhere\]/);
  assert.match(page, />Page not found</);
  assert.doesNotMatch(page, /Page Not Found|bg-slate-50/);
});

test('browser navigation closes the menu, and the menu reopens at its top', () => {
  const nav = read('src/components/UnderlayNav.jsx');
  assert.match(nav, /useEffect\(\(\) => \{\s*closeMenuRef\.current\?\.\(\);\s*\}, \[location\]\);/);
  assert.match(nav, /if \(isOpen\) \{\s*(\/\/[^\n]*\n\s*)*if \(innerEl\) innerEl\.scrollTop = 0;/);
});

test('Generate Report without a company is idle: no Loading..., no LIVE step', () => {
  const page = read('src/pages/GenerateReport.jsx');
  assert.match(page, /\{headerName \|\| \(noTarget \? "No company selected" : "Loading\.\.\."\)\}/);
  assert.match(page, /const active = !noTarget && !isError && i === stepIdx && !isComplete && !isQueued;/);
});


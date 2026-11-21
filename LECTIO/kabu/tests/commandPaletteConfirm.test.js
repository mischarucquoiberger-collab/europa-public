// Command palette (Cmd/Ctrl+K): typing a ticker and pressing Enter must not start a paid report.
// The real component is compiled and mounted in a small in-memory React host; only the router,
// storage and scroll-lock helpers are substituted.
import test, { afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import React from 'react';
import { build } from 'esbuild';

const require = createRequire(import.meta.url);
const Reconciler = require('react-reconciler');
const { ConcurrentRoot, DefaultEventPriority } = require('react-reconciler/constants');

const navigations = [];
const substitutes = {
  'react-router-dom': { useNavigate: () => (to) => { navigations.push(to); } },
  '@/lib/safeUrl': { safeSameOriginPath: (value) => value },
  '@/lib/reportStorage': { readReportHistory: () => [] },
  '@/lib/bodyScrollLock': { acquireBodyScrollLock: () => () => {} },
  '@/lib/features': { DEEP_RESEARCH_ENABLED: true },
};
const output = await build({
  entryPoints: [fileURLToPath(new URL('../src/components/CommandPalette.jsx', import.meta.url))],
  bundle: true, write: false, platform: 'node', format: 'cjs', jsx: 'automatic',
  external: ['react', 'react/*'], alias: { '@': fileURLToPath(new URL('../src', import.meta.url)) },
  logLevel: 'silent',
  plugins: [{ name: 'palette-substitutes', setup(b) {
    b.onResolve({ filter: /^(@\/|react-router-dom$)/ }, (args) => (args.path in substitutes ? { path: args.path, external: true } : undefined));
  } }],
});
const compiled = { exports: {} };
new Function('require', 'module', 'exports', output.outputFiles[0].text)(
  (name) => (name in substitutes ? substitutes[name] : require(name)), compiled, compiled.exports);
const CommandPalette = compiled.exports.default;

// ── Minimal browser surface ──────────────────────────────────────────────────
const listeners = new Set();
globalThis.window = { addEventListener: (type, fn) => type === 'keydown' && listeners.add(fn), removeEventListener: (type, fn) => listeners.delete(fn) };
globalThis.HTMLElement = class {};
globalThis.document = {
  body: { getAttribute: () => null }, activeElement: null,
  getElementById: () => null, querySelector: () => null,
};
const press = (key, extra = {}) => { for (const fn of [...listeners]) fn({ key, preventDefault() {}, ...extra }); };

function createHost() {
  const container = { children: [] };
  const detach = (list, child) => { const at = list.indexOf(child); if (at !== -1) list.splice(at, 1); };
  const place = (list, child, before) => {
    detach(list, child);
    const at = before ? list.indexOf(before) : -1;
    if (at === -1) list.push(child); else list.splice(at, 0, child);
  };
  const renderer = Reconciler({
    supportsMutation: true, supportsPersistence: false, supportsHydration: false, isPrimaryRenderer: false,
    supportsMicrotasks: true, scheduleMicrotask: queueMicrotask,
    scheduleTimeout: setTimeout, cancelTimeout: clearTimeout, noTimeout: -1,
    getCurrentEventPriority: () => DefaultEventPriority,
    getRootHostContext: () => null, getChildHostContext: (context) => context,
    createInstance: (type, props) => ({ type, props, children: [], focus() {}, querySelector: () => null, querySelectorAll: () => [] }),
    createTextInstance: (text) => ({ text }),
    appendInitialChild: (parent, child) => { parent.children.push(child); },
    appendChild: (parent, child) => place(parent.children, child, null),
    appendChildToContainer: (root, child) => place(root.children, child, null),
    insertBefore: (parent, child, before) => place(parent.children, child, before),
    insertInContainerBefore: (root, child, before) => place(root.children, child, before),
    removeChild: (parent, child) => detach(parent.children, child),
    removeChildFromContainer: (root, child) => detach(root.children, child),
    clearContainer: (root) => { root.children.length = 0; },
    finalizeInitialChildren: () => false, prepareUpdate: () => true,
    commitUpdate: (node, _payload, _type, _previous, props) => { node.props = props; },
    commitTextUpdate: (node, _previous, text) => { node.text = text; },
    shouldSetTextContent: () => false, getPublicInstance: (node) => node,
    prepareForCommit: () => null, resetAfterCommit() {}, preparePortalMount() {},
    commitMount() {}, resetTextContent() {}, detachDeletedInstance() {},
    hideInstance() {}, unhideInstance() {}, hideTextInstance() {}, unhideTextInstance() {},
    getInstanceFromNode: () => null, beforeActiveInstanceBlur() {}, afterActiveInstanceBlur() {},
    prepareScopeUpdate() {}, getInstanceFromScope: () => null,
  });
  return { renderer, container };
}

const turn = () => new Promise((resolve) => setImmediate(resolve));
async function settle() { for (let i = 0; i < 12; i += 1) await turn(); }
const textOf = (node) => ('text' in node ? String(node.text) : node.children.map(textOf).join(' '));
const flat = (node) => textOf(node).replace(/\s+/g, ' ').trim();
function findAll(node, match, found = []) {
  if ('text' in node) return found;
  if (node.type && match(node)) found.push(node);
  for (const child of node.children) findAll(child, match, found);
  return found;
}

const mounted = [];
async function openPalette() {
  navigations.length = 0;
  const { renderer, container } = createHost();
  const root = renderer.createContainer(container, ConcurrentRoot, null, false, null, '', (error) => { throw error; }, null);
  renderer.updateContainer(React.createElement(CommandPalette), root, null, null);
  mounted.push(() => renderer.updateContainer(null, root, null, null));
  await settle();
  press('k', { metaKey: true });
  await settle();
  return container;
}
afterEach(async () => {
  while (mounted.length) mounted.pop()();
  await settle();
});

const input = (page) => findAll(page, (n) => n.type === 'input')[0];
async function typeInto(page, value) { input(page).props.onChange({ target: { value } }); await settle(); }
async function enter(page) { input(page).props.onKeyDown({ key: 'Enter', preventDefault() {} }); await settle(); }
const confirmBar = (page) => findAll(page, (n) => n.props.className === 'cmdk-confirm')[0];
const buttonNamed = (page, label) => findAll(page, (n) => n.type === 'button' && flat(n) === label)[0];

test('Enter on a ticker only arms the row; the second Enter starts the report', async () => {
  const page = await openPalette();
  await typeInto(page, 'aapl');
  await enter(page);
  assert.deepEqual(navigations, [], 'nothing starts on the first Enter');
  assert.ok(confirmBar(page), 'a confirm step is shown');
  assert.match(flat(confirmBar(page)), /starts a paid report/i);
  assert.match(flat(page), /Press Enter again to confirm/);
  await enter(page);
  assert.deepEqual(navigations, ['/GenerateReport?ticker=AAPL']);
});

test('the Generate report button confirms; Cancel and a changed query disarm', async () => {
  const page = await openPalette();
  await typeInto(page, 'aapl');
  await enter(page);
  await buttonNamed(page, 'Cancel').props.onClick();
  await settle();
  assert.equal(confirmBar(page), undefined);
  await enter(page);                       // armed again
  await typeInto(page, 'aaplx');           // a changed query disarms
  assert.equal(confirmBar(page), undefined);
  assert.deepEqual(navigations, []);
  await typeInto(page, 'msft');
  await enter(page);
  buttonNamed(page, 'Generate report').props.onClick();
  await settle();
  assert.deepEqual(navigations, ['/GenerateReport?ticker=MSFT']);
});

test('clicking the ticker row arms it too, and ordinary rows still open at once', async () => {
  const page = await openPalette();
  await typeInto(page, 'aapl');
  const rows = findAll(page, (n) => n.type === 'button' && n.props.className?.startsWith('cmdk-item'));
  rows[0].props.onClick();
  await settle();
  assert.deepEqual(navigations, [], 'the first click arms, it does not start');
  assert.ok(confirmBar(page));
  await typeInto(page, 'deep');
  const deep = findAll(page, (n) => n.type === 'button' && /Callisto/.test(flat(n)))[0];
  deep.props.onClick();
  await settle();
  assert.deepEqual(navigations, ['/DeepResearch']);
  // LECTIO: typed text no longer offers a jump into the screener.
  assert.equal(findAll(page, (n) => n.type === 'button' && /Search the screener/.test(flat(n))).length, 0);
});

const rowLabels = (page) => findAll(page, (n) => n.type === 'button' && n.props.className?.startsWith('cmdk-item'))
  .map((n) => flat(findAll(n, (c) => c.props.className === 'cmdk-label')[0]));

test('a US ticker in any case offers its report; an ordinary word never offers a ticker report', async () => {
  const page = await openPalette();
  await typeInto(page, 'aapl');
  assert.equal(rowLabels(page)[0], 'Generate research report for AAPL');
  assert.match(flat(page), /Apple Inc\. · Report mode/);
  assert.equal(rowLabels(page).filter((l) => /AAPL|Apple/.test(l)).length, 1, 'the company is not listed twice');
  await typeInto(page, 'BRK-B');
  assert.equal(rowLabels(page)[0], 'Generate research report for BRK.B');
  await typeInto(page, 'home');
  assert.deepEqual(rowLabels(page), ['Home'], '"home" offers only the Home page');
  await enter(page);
  assert.deepEqual(navigations, ['/Home']);
});

test('"reports", "apple" and unlisted symbols: no ticker report for HOME/REPORTS/APPLE/ZZZZ', async () => {
  const page = await openPalette();
  await typeInto(page, 'reports');
  assert.deepEqual(rowLabels(page), ['Reports']);
  await typeInto(page, 'apple');
  assert.deepEqual(rowLabels(page), ['Apple Inc.'], 'the company by name, not a ticker called APPLE');
  await typeInto(page, 'zzzz');
  assert.deepEqual(rowLabels(page), []);
  assert.match(flat(page), /No matches — try a page name or a US ticker\./);
  assert.ok(!navigations.length);
});

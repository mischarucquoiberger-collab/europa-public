// Focus after a route change (src/lib/NavigationTracker.jsx). The real module
// is compiled from source; React's two hooks it uses (useRef, useEffect) run on
// a small hook runtime with React's commit order, the router location is the
// test's, and the document is a fixture that records focus. A navigation is:
// the old page unmounts (focus falls back to <body>), the new page commits and
// may focus its own field, then effects run and the next animation frame fires.
import test, { afterEach, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';

const require = createRequire(import.meta.url);
const SOURCE = fileURLToPath(new URL('../src/lib/NavigationTracker.jsx', import.meta.url));

// --- hook runtime: one component instance at a time ------------------------
let instance = null;
const hookRuntime = {
  useRef(initial) {
    const slot = instance.cursor++;
    if (!(slot in instance.slots)) instance.slots[slot] = { current: initial };
    return instance.slots[slot];
  },
  useEffect(effect, deps) {
    const slot = instance.cursor++;
    const previous = instance.slots[slot];
    const changed = !previous || !deps || deps.length !== previous.deps.length
      || deps.some((dep, index) => !Object.is(dep, previous.deps[index]));
    if (!changed) return;
    const owner = instance;
    owner.pending.push(() => {
      previous?.cleanup?.();
      const cleanup = effect();
      owner.slots[slot] = { deps, cleanup: typeof cleanup === 'function' ? cleanup : undefined };
    });
  },
};

const substitutes = {
  react: hookRuntime,
  'react-router-dom': { useLocation: () => instance.location },
};

let compiled;
function trackerModule() {
  compiled ??= build({
    entryPoints: [SOURCE],
    bundle: true, write: false, platform: 'node', format: 'cjs', jsx: 'automatic',
    external: [...Object.keys(substitutes), 'react/*'],
    logLevel: 'silent',
  }).then(output => {
    const module = { exports: {} };
    const load = name => (name in substitutes ? substitutes[name] : require(name));
    new Function('require', 'module', 'exports', output.outputFiles[0].text)(load, module, module.exports);
    return module.exports;
  });
  return compiled;
}
const { default: NavigationTracker } = await trackerModule();

// --- document and animation frames ------------------------------------------
let doc;
let frames;
function element(tagName, label = tagName) {
  return {
    tagName, label, isConnected: true, attributes: {},
    setAttribute(name, value) { this.attributes[name] = String(value); },
    focus(options) { doc.activeElement = this; doc.focusCalls.push({ target: this.label, options }); },
  };
}
// A rendered screen: its first <h1> and <main> are what the tracker may focus.
function screen(name, { h1 = true, main = true } = {}) {
  return { name, h1: h1 ? element('H1', `${name} heading`) : null, main: main ? element('MAIN', `${name} main`) : null };
}

beforeEach(() => {
  doc = { title: '', focusCalls: [], current: null };
  doc.body = element('BODY', 'body');
  doc.documentElement = element('HTML', 'html');
  doc.activeElement = doc.body;
  doc.querySelector = selector => {
    if (selector === 'h1') return doc.current?.h1 ?? null;
    if (selector === 'main') return doc.current?.main ?? null;
    throw new Error(`unexpected selector ${selector}`);
  };
  frames = new Map();
  let nextFrame = 0;
  globalThis.document = doc;
  globalThis.requestAnimationFrame = callback => { nextFrame += 1; frames.set(nextFrame, callback); return nextFrame; };
  globalThis.cancelAnimationFrame = id => { frames.delete(id); };
});
afterEach(() => {
  delete globalThis.document;
  delete globalThis.requestAnimationFrame;
  delete globalThis.cancelAnimationFrame;
});

function runFrames() {
  const pending = [...frames.values()];
  frames.clear();
  for (const callback of pending) callback();
}

/**
 * Mount the tracker on `pathname` with `page` on screen. `focus` is the
 * element the page focuses while it commits (autoFocus / mount effects).
 */
function mount(pathname, page, { focus = null } = {}) {
  const self = { slots: [], cursor: 0, pending: [], location: { pathname } };
  const commit = (next, focused) => {
    instance = self;
    self.cursor = 0;
    NavigationTracker();
    instance = null;
    doc.current = next;
    if (focused) focused.focus({ preventScroll: true });
    doc.focusCalls = [];
    for (const effect of self.pending.splice(0)) effect();
  };
  commit(page, focus);
  return {
    /** Go to `nextPath`; the previous page unmounts unless `persist` keeps the same screen mounted. */
    navigate(nextPath, nextPage, { focus: focused = null, persist = false } = {}) {
      if (!persist) {
        if (doc.activeElement !== doc.body) doc.activeElement.isConnected = false;
        doc.activeElement = doc.body;
      }
      self.location = { pathname: nextPath };
      commit(nextPage, focused);
    },
    unmount() { for (const slot of self.slots) slot?.cleanup?.(); },
  };
}

// ---------------------------------------------------------------------------

test('the first screen keeps the focus it set; only the tab title follows the route', () => {
  const query = screen('query');
  const composer = element('TEXTAREA', 'composer');
  mount('/DeepResearch', query, { focus: composer });
  assert.equal(doc.title, 'Callisto · Europa');
  assert.equal(frames.size, 0, 'no heading focus is scheduled on the first screen');
  assert.equal(doc.activeElement, composer);
});

test('the root and an unlisted route title the tab "Europa" alone', () => {
  const tracker = mount('/', screen('root'));
  assert.equal(doc.title, 'Europa');
  tracker.navigate('/NoSuchRoute', screen('fallback'));
  assert.equal(doc.title, 'Europa');
  tracker.navigate('/Home', screen('home'));
  assert.equal(doc.title, 'Home · Europa');
  tracker.navigate('/Reports', screen('reports', { h1: false, main: false }));
  assert.equal(doc.title, 'Research Reports · Europa');
});

test('a new page gets its heading, then its main landmark, then nothing at all', () => {
  const tracker = mount('/Home', screen('home'));
  const reports = screen('reports');
  tracker.navigate('/Reports', reports);
  runFrames();
  assert.equal(doc.activeElement, reports.h1);
  assert.deepEqual(reports.h1.attributes, { tabindex: '-1' });
  assert.deepEqual(doc.focusCalls, [{ target: 'reports heading', options: { preventScroll: true } }]);

  const loading = screen('loading', { h1: false });
  tracker.navigate('/GenerateReport', loading);
  runFrames();
  assert.equal(doc.activeElement, loading.main);
  const bare = screen('bare', { h1: false, main: false });
  tracker.navigate('/Viewer', bare);
  runFrames();
  assert.equal(doc.activeElement, doc.body);
});

test('pages take the heading focus, even when a control stays focused across the navigation', () => {
  const home = screen('home');
  const tracker = mount('/Home', home);
  const search = element('INPUT', 'header search');
  search.focus();
  const query = screen('query');
  tracker.navigate('/DeepResearch', query, { persist: true });
  assert.equal(doc.title, 'Callisto · Europa');
  runFrames();
  assert.equal(doc.activeElement, query.h1, 'the new page heading is announced');
  assert.deepEqual(query.h1.attributes, { tabindex: '-1' });

  // A field the new page focused while mounting does not keep the focus either.
  const reports = screen('reports');
  tracker.navigate('/Reports', reports, { focus: element('INPUT', 'report search') });
  runFrames();
  assert.equal(doc.activeElement, reports.h1);
});

test('a navigation overtaken before its frame, or an unmount, moves no focus', () => {
  const tracker = mount('/Home', screen('home'));
  tracker.navigate('/Reports', screen('reports'));
  const field = element('INPUT', 'query field');
  const query = screen('query');
  tracker.navigate('/DeepResearch', query, { focus: field, persist: true });
  assert.equal(frames.size, 1, 'the earlier frame was cancelled');
  runFrames();
  assert.equal(doc.activeElement, query.h1);

  tracker.navigate('/Reports', screen('reports'));
  tracker.unmount();
  assert.equal(frames.size, 0);
  runFrames();
  assert.equal(doc.activeElement, doc.body);
});

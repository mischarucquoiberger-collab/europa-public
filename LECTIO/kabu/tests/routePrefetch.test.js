import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { prefetchMenuRoutes, prefetchRoute, registerRouteImporters, __test } from '../src/lib/routePrefetch.js';

test('a registered route chunk is fetched once; unknown routes and query strings are handled', async () => {
  __test.started.clear();
  let calls = 0;
  registerRouteImporters({ '/Query': async () => { calls += 1; return { default: 'Query' }; } });
  await prefetchRoute('/Query');
  await prefetchRoute('/Query?x=1');
  assert.equal(calls, 1);
  assert.equal(prefetchRoute('/Nope'), null);
});

test('a failed chunk download may be tried again; Save-Data and 2G skip prefetch', async () => {
  __test.started.clear();
  let calls = 0;
  const importers = { '/Flaky': async () => { calls += 1; throw new Error('offline'); } };
  await prefetchRoute('/Flaky', { importers });
  await prefetchRoute('/Flaky', { importers });
  assert.equal(calls, 2);
  assert.equal(prefetchRoute('/Flaky', { importers, nav: { connection: { saveData: true } } }), null);
  assert.equal(prefetchRoute('/Flaky', { importers, nav: { connection: { effectiveType: 'slow-2g' } } }), null);
});

test('opening the menu fetches every registered menu route on idle time, one after another', async () => {
  __test.started.clear();
  const loaded = [];
  const importers = { '/A': async () => loaded.push('A'), '/B': async () => loaded.push('B') };
  const idle = [];
  const win = { navigator: {}, requestIdleCallback: (fn) => { idle.push(fn); return idle.length; }, cancelIdleCallback() {} };
  prefetchMenuRoutes(['/A', '/DeepResearch', '/B'], { win, importers });
  while (idle.length) { idle.shift()(); await new Promise((r) => setImmediate(r)); }
  assert.deepEqual(loaded, ['A', 'B']);
});

test('pages.config registers exactly the menu routes for prefetch', () => {
  const cfg = readFileSync(new URL('../src/pages.config.js', import.meta.url), 'utf8');
  const block = cfg.slice(cfg.indexOf('registerRouteImporters({'), cfg.indexOf('});', cfg.indexOf('registerRouteImporters({')));
  for (const route of ['/Home', '/Reports']) assert.match(block, new RegExp(`"${route}"`));
  // Deep Research is left out: its page owns its own workspace preload.
  assert.deepEqual([...block.matchAll(/"(\/[A-Za-z]+)":/g)].map(m => m[1]), ['/Home', '/Reports']);
});

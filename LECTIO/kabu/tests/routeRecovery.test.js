import test from 'node:test';
import assert from 'node:assert/strict';
import { isChunkFailure, loadRoute, observePreloadFailure } from '../src/lib/routeRecovery.js';

test('successful route loads once; transient chunk failure retries once', async () => {
  const module = { default: () => null };
  let calls = 0;
  const waits = [];
  assert.equal(await loadRoute(async () => module), module);
  assert.equal(await loadRoute(async () => {
    if (++calls === 1) throw new TypeError('Failed to fetch dynamically imported module: /static/route.js');
    return module;
  }, async ms => waits.push(ms)), module);
  assert.equal(calls, 2);
  assert.deepEqual(waits, [300]);
});

test('persistent failure rejects after two attempts without navigation/reload', async () => {
  let calls = 0;
  const error = new TypeError('Importing a module script failed.');
  await assert.rejects(loadRoute(async () => { calls++; throw error; }, async () => {}), error);
  assert.equal(calls, 2);
});

test('ordinary module error is not retried or mislabelled as transport failure', async () => {
  let calls = 0;
  const error = new Error('module configuration invalid');
  await assert.rejects(loadRoute(async () => { calls++; throw error; }), error);
  assert.equal(calls, 1);
  assert.equal(isChunkFailure(error), false);
  assert.equal(isChunkFailure(null), false);
});

test('Vite CSS preloads remain rejected and reach recovery without swallowing errors', async () => {
  let prevented = false;
  const error = new Error('CSS request disconnected');
  observePreloadFailure({ payload: error, preventDefault() { prevented = true; } });
  assert.equal(prevented, false);
  assert.equal(isChunkFailure(error), true);
  let calls = 0;
  await assert.rejects(loadRoute(async () => { calls++; throw error; }, async () => {}), error);
  assert.equal(calls, 2);
});

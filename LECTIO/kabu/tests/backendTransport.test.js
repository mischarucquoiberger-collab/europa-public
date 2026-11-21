import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';

// Bundle the actual endpoint adapter: request/response handling is production code.
const compiled = await build({ stdin: { contents: 'export * from "./src/api/backend.js";', resolveDir: fileURLToPath(new URL('..', import.meta.url)) },
  bundle: true, write: false, platform: 'node', format: 'cjs', logLevel: 'silent' });
const module = { exports: {} };
new Function('require', 'module', 'exports', compiled.outputFiles[0].text)(createRequire(import.meta.url), module, module.exports);
const backend = module.exports;

function setup(t) {
  const old = Object.getOwnPropertyDescriptors(globalThis);
  Object.assign(globalThis, { location: { href: 'https://indago.example/' }, localStorage: { getItem: () => null, removeItem() {} } });
  t.after(() => {
    for (const key of ['location', 'localStorage', 'fetch', 'setTimeout', 'clearTimeout']) {
      if (old[key]) Object.defineProperty(globalThis, key, old[key]); else delete globalThis[key];
    }
  });
}

for (const [name, path, args] of [
  ['streamChat', '/api/chat', [[{ role: 'user', content: 'hello' }]]],
  ['streamReportChat', '/api/report-chat', ['a'.repeat(32), []]],
]) {
  test(`${name} keeps one POST with no credential header, caller cancellation and chunked SSE`, async t => {
    setup(t);
    const calls = [], text = [], errors = [];
    let done = 0;
    const signal = new AbortController().signal;
    globalThis.fetch = async (url, options) => {
      calls.push([url, options]);
      return new Response(new ReadableStream({ start(controller) {
        for (const part of ['event: text\nda', 'ta: {"text":"hello"}\n\n', 'event: done\ndata: {}\n\n']) controller.enqueue(new TextEncoder().encode(part));
        controller.close();
      } }));
    };
    await backend[name](...args, { signal, onText: value => text.push(value), onError: error => errors.push(error), onDone: () => done++ });
    assert.equal(calls.length, 1);
    assert.equal(calls[0][0], path);
    assert.equal(calls[0][1].method, 'POST');
    assert.equal(calls[0][1].signal, signal);
    // There is no sign-in: requests carry no Authorization header.
    const headers = new Headers(calls[0][1].headers);
    assert.equal(headers.get('Authorization'), null);
    assert.equal(headers.get('Content-Type'), 'application/json');
    assert.deepEqual(text, ['hello']);
    assert.deepEqual(errors, []);
    assert.equal(done, 1);
  });

  test(`${name} never retries aborted paid POST or presents abort as a server error`, async t => {
    setup(t);
    let calls = 0;
    const errors = [];
    globalThis.fetch = async () => { calls++; throw new DOMException('user stopped', 'AbortError'); };
    await backend[name](...args, { onError: error => errors.push(error) });
    assert.equal(calls, 1);
    assert.deepEqual(errors, []);
  });
}

test('price-history retains its 20-second caller-owned deadline and clears the timer', async t => {
  setup(t);
  let timer, cleared = false, signal;
  globalThis.setTimeout = (callback, ms) => { assert.equal(ms, 20_000); timer = callback; return 123; };
  globalThis.clearTimeout = id => { assert.equal(id, 123); cleared = true; };
  globalThis.fetch = async (_url, options) => {
    signal = options.signal; timer();
    assert.equal(signal.aborted, true);
    throw new DOMException('timed out', 'AbortError');
  };
  await backend.fetchPriceHistory('7203');
  assert.equal(cleared, true);
});

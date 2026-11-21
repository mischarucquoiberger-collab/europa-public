// Home re-checks Recent rows still saved as "warning" (S14). Bundles the real
// Home.jsx export with the real /status client (api/backend.js + api/http.js)
// and the real report history store (lib/reportStorage.js); only fetch, the
// browser store and Home's UI imports are substituted.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';

const require = createRequire(import.meta.url);
const homePath = fileURLToPath(new URL('../src/pages/Home.jsx', import.meta.url));
const homeSource = readFileSync(homePath, 'utf8');
const REAL = {
  '@/api/backend': fileURLToPath(new URL('../src/api/backend.js', import.meta.url)),
  '@/lib/reportStorage': fileURLToPath(new URL('../src/lib/reportStorage.js', import.meta.url)),
};

// Named imports of each UI module Home uses, so its stub can export them.
const importedNames = {};
for (const [, clause, from] of homeSource.matchAll(/import\s+([\s\S]*?)\s+from\s+["']([^"']+)["']/g)) {
  const names = (clause.match(/\{([\s\S]*)\}/)?.[1] || '').split(',').map((n) => n.trim().split(/\s+as\s+/)[0]).filter(Boolean);
  importedNames[from] = names;
}
const stubs = {
  name: 'home-ui-stubs',
  setup(builder) {
    builder.onResolve({ filter: /\.webp$/ }, ({ path }) => ({ path, namespace: 'stub-image' }));
    builder.onLoad({ filter: /.*/, namespace: 'stub-image' }, () => ({ contents: 'export default "image.webp";', loader: 'js' }));
    builder.onResolve({ filter: /.*/ }, ({ path, importer }) => {
      if (importer !== homePath) return undefined;
      if (path === 'react' || path.startsWith('react/')) return { path, external: true };
      if (REAL[path]) return { path: REAL[path] };
      return { path, namespace: 'stub-ui' };
    });
    builder.onLoad({ filter: /.*/, namespace: 'stub-ui' }, ({ path }) => ({
      contents: ['function Stub() { return null; }', 'export default Stub;',
        ...(importedNames[path] || []).map((n) => `export const ${n} = Stub;`)].join('\n'),
      loader: 'js',
    }));
  },
};
const compiled = await build({
  stdin: {
    contents: [
      `export { resyncWarningHistory } from ${JSON.stringify(homePath)};`,
      `export { getStatus } from ${JSON.stringify(REAL['@/api/backend'])};`,
      `export { createReportStorage, REPORT_HISTORY_PREFIX } from ${JSON.stringify(REAL['@/lib/reportStorage'])};`,
    ].join('\n'),
    resolveDir: fileURLToPath(new URL('..', import.meta.url)),
  },
  bundle: true, write: false, platform: 'node', format: 'cjs', jsx: 'automatic', logLevel: 'silent',
  external: ['react', 'react/*'], loader: { '.css': 'empty' }, plugins: [stubs],
});
const mod = { exports: {} };
new Function('require', 'module', 'exports', compiled.outputFiles[0].text)(require, mod, mod.exports);
const { resyncWarningHistory, getStatus, createReportStorage, REPORT_HISTORY_PREFIX } = mod.exports;

// ── Fixtures ─────────────────────────────────────────────────────────────────
function memoryStorage() {
  const data = new Map();
  return {
    get length() { return data.size; },
    key: (i) => [...data.keys()][i] ?? null,
    getItem: (k) => (data.has(k) ? data.get(k) : null),
    setItem: (k, v) => { data.set(k, String(v)); },
    removeItem: (k) => { data.delete(k); },
  };
}
const jobId = (n) => n.toString(16).padStart(32, '0');
const row = (n, status, extra = {}) => ({
  jobId: jobId(n), ticker: '7203', companyName: 'Toyota Motor Corporation',
  html_file: `report_7203_${n.toString(16).padStart(8, '0')}.html`, pdf_file: `report_7203_${n.toString(16).padStart(8, '0')}.pdf`,
  finishedAt: new Date(Date.UTC(2026, 9, 1, 0, n)).toISOString(), sources: [{ title: 'TDnet', url: 'https://example.com/a', type: 'web' }],
  status, warning: status === 'warning' ? 'Report available with narrative limitations.' : null, ...extra,
});

function setup(t, respond) {
  const old = Object.getOwnPropertyDescriptors(globalThis);
  const calls = [];
  let inFlight = 0, maxInFlight = 0;
  Object.assign(globalThis, {
    location: { href: 'https://indago.example/', origin: 'https://indago.example' },
    localStorage: memoryStorage(),
    fetch: async (url, init) => {
      calls.push({ url: String(url), init });
      inFlight += 1; maxInFlight = Math.max(maxInFlight, inFlight);
      try {
        await new Promise((r) => setTimeout(r, 5));
        const id = String(url).split('/').pop();
        const out = await respond(id, String(url));
        if (out instanceof Error) throw out;
        const { status = 200, body = {} } = out;
        return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
      } finally { inFlight -= 1; }
    },
  });
  t.after(() => {
    for (const key of ['location', 'localStorage', 'fetch']) {
      if (old[key]) Object.defineProperty(globalThis, key, old[key]); else delete globalThis[key];
    }
  });
  const store = createReportStorage();
  return { store, calls, stats: () => ({ maxInFlight }) };
}
const deps = (store, extra = {}) => ({
  fetchStatus: getStatus, findEntry: store.findReportHistory, saveEntry: store.upsertReportHistory,
  seen: new Map(), ...extra,
});
const raw = (n) => globalThis.localStorage.getItem(`${REPORT_HISTORY_PREFIX}${jobId(n)}`);

// ── Tests ────────────────────────────────────────────────────────────────────
test('warning row whose /status now says complete is saved as complete with no warning; nothing else changes', async (t) => {
  const { store, calls } = setup(t, (id) => ({ body: { job_id: id, status: 'complete', message: 'Report ready' } }));
  store.upsertReportHistory(row(1, 'warning'));
  const before = JSON.parse(raw(1));
  let changes = 0;
  await resyncWarningHistory(store.readReportHistory(), deps(store, { onChange: () => { changes += 1; } }));
  const after = JSON.parse(raw(1));
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, `/status/${jobId(1)}`);
  assert.equal(after.status, 'complete');
  assert.equal(after.warning, null);
  assert.deepEqual({ ...after, status: before.status, warning: before.warning }, before, 'only status and warning change');
  assert.deepEqual(Object.keys(after), Object.keys(before), 'same storage shape');
  assert.equal(changes, 1);
  assert.equal(store.readReportHistory()[0].status, 'complete');
});

for (const [name, respond] of [
  ['404', (id) => ({ status: 404, body: { detail: 'Job not found' } })],
  ['401', (id) => ({ status: 401, body: { detail: 'Not authenticated' } })],
  ['network error', () => new TypeError('Failed to fetch')],
  ['still warning', (id) => ({ body: { job_id: id, status: 'warning', message: 'HTML ready. PDF failed' } })],
  ['running', (id) => ({ body: { job_id: id, status: 'running' } })],
  ['a different job id', () => ({ body: { job_id: jobId(999), status: 'complete' } })],
]) {
  test(`${name}: the warning row is left byte-for-byte unchanged`, async (t) => {
    const { store, calls } = setup(t, respond);
    store.upsertReportHistory(row(2, 'warning'));
    const before = raw(2);
    let changes = 0;
    await resyncWarningHistory(store.readReportHistory(), deps(store, { onChange: () => { changes += 1; } }));
    assert.equal(calls.length, 1);
    assert.equal(raw(2), before);
    assert.equal(changes, 0);
  });
}

test('only the 20 newest warning rows are checked, at most 3 at a time; complete rows are never requested', async (t) => {
  const { store, calls, stats } = setup(t, (id) => ({ body: { job_id: id, status: 'complete' } }));
  for (let n = 1; n <= 25; n += 1) store.upsertReportHistory(row(n, 'warning'));
  for (let n = 26; n <= 30; n += 1) store.upsertReportHistory(row(n, 'complete'));
  const rows = store.readReportHistory();
  await resyncWarningHistory(rows, deps(store));
  const asked = calls.map((c) => c.url.split('/').pop());
  const newestWarnings = rows.filter((r) => r.status === 'warning').slice(0, 20).map((r) => r.jobId);
  assert.equal(calls.length, 20);
  assert.deepEqual([...asked].sort(), [...newestWarnings].sort());
  assert.ok(stats().maxInFlight <= 3, `max in flight ${stats().maxInFlight}`);
  assert.equal(stats().maxInFlight, 3);
  for (let n = 1; n <= 5; n += 1) assert.equal(JSON.parse(raw(n)).status, 'warning', 'the 5 oldest stay unchecked');
  for (let n = 6; n <= 25; n += 1) assert.equal(JSON.parse(raw(n)).status, 'complete');
});

test('each job is requested once per page load (a remount reuses the first answer)', async (t) => {
  const { store, calls } = setup(t, (id) => ({ body: { job_id: id, status: 'warning' } }));
  store.upsertReportHistory(row(3, 'warning'));
  const seen = new Map();
  await resyncWarningHistory(store.readReportHistory(), deps(store, { seen }));
  await resyncWarningHistory(store.readReportHistory(), deps(store, { seen }));
  assert.equal(calls.length, 1);
});

test('unmount cancels: no further requests start and late answers are not applied', async (t) => {
  let cancelled = false;
  const { store, calls } = setup(t, (id) => { cancelled = true; return { body: { job_id: id, status: 'complete' } }; });
  for (let n = 1; n <= 8; n += 1) store.upsertReportHistory(row(n, 'warning'));
  const before = Object.fromEntries([1, 2, 3, 4, 5, 6, 7, 8].map((n) => [n, raw(n)]));
  await resyncWarningHistory(store.readReportHistory(), deps(store, { isCancelled: () => cancelled }));
  assert.equal(calls.length, 3, 'only the first wave was in flight');
  for (let n = 1; n <= 8; n += 1) assert.equal(raw(n), before[n]);
});

test('a row the user deleted or that already changed meanwhile is not resurrected or rewritten', async (t) => {
  const { store } = setup(t, (id) => ({ body: { job_id: id, status: 'complete' } }));
  store.upsertReportHistory(row(4, 'warning'));
  store.upsertReportHistory(row(5, 'warning'));
  const rows = store.readReportHistory();
  store.removeReportHistory(jobId(4));
  store.upsertReportHistory({ ...row(5, 'warning'), sources: [] });
  await resyncWarningHistory(rows, deps(store));
  assert.equal(raw(4), null);
  assert.deepEqual(JSON.parse(raw(5)).sources, []);
  assert.equal(JSON.parse(raw(5)).status, 'complete');
});

test('Home wires the re-check to the app status client and history store, and keeps the badge rule', () => {
  const effect = homeSource.slice(homeSource.indexOf('resyncWarningHistory(readReportHistory(), {'));
  assert.match(effect, /fetchStatus: getStatus,/);
  assert.match(effect, /findEntry: findReportHistory,/);
  assert.match(effect, /saveEntry: upsertReportHistory,/);
  assert.match(effect, /isCancelled: \(\) => cancelled,/);
  assert.match(effect, /return \(\) => \{ cancelled = true; \};/);
  assert.match(homeSource, /const RESYNC_MAX_ROWS = 20;/);
  assert.match(homeSource, /const RESYNC_MAX_IN_FLIGHT = 3;/);
  assert.match(homeSource, /const warningText = item\.warning \|\| \(item\.status === "warning" \? "Report completed with a warning\." : null\);/);
  assert.match(homeSource, /\{item\.pdf \? "Warning" : "HTML only"\}/);
});

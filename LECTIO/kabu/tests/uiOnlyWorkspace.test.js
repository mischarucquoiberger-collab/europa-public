// The UI-only Deep Research workspace: the built client in public/xyz is served with fixed
// start-up answers (dev/uiOnlyWorkspace.js), so its real screen opens after the splash without
// any research service. A question gets "not connected", never a made-up answer.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import {
  NOT_CONNECTED, WORKSPACE_BASE, bridgeProbe, bridgeTarget, hostAnswer, isBridgeRequest, workspaceAnswer,
  workspaceMiddleware,
} from '../dev/uiOnlyWorkspace.js';

const root = fileURLToPath(new URL('../', import.meta.url));
const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');
const body = (answer) => JSON.parse(answer.body);

test('start-up answers: a guest session, the Indago lane with its two models, empty lists', () => {
  assert.equal(WORKSPACE_BASE, '/xyz');
  const session = body(workspaceAnswer('POST', '/api/auth/refresh'));
  assert.equal(typeof session.token, 'string');
  assert.equal(session.user.email, 'guest@example.com');          // made-up, no real person
  assert.deepEqual(body(workspaceAnswer('GET', '/api/models')), { Indago: ['indago-query', 'indago-deep-research'] });
  const endpoints = body(workspaceAnswer('GET', '/api/endpoints'));
  assert.deepEqual(Object.keys(endpoints), ['Indago']);            // the lane id the client's code expects
  assert.equal(endpoints.Indago.modelDisplayLabel, 'Callisto');
  const config = body(workspaceAnswer('GET', '/api/config'));
  assert.equal(config.appTitle, 'Callisto');
  assert.equal(config.customFooter, '');
  assert.deepEqual(body(workspaceAnswer('GET', '/api/convos?limit=25')), { conversations: [], nextCursor: null });
  assert.deepEqual(body(workspaceAnswer('GET', '/api/projects')), { projects: [], nextCursor: null });
  assert.equal(workspaceAnswer('GET', '/health').body, 'OK');
  const role = body(workspaceAnswer('GET', '/api/roles/USER'));
  assert.equal(role.permissions.BOOKMARKS.USE, true);
  assert.equal(role.permissions.TEMPORARY_CHAT.USE, true);
});

test('nothing is answered for the model: a sent question gets "not connected"', () => {
  for (const path of ['/api/agents/chat/Indago', '/api/files', '/api/convos/update', '/api/messages/abc']) {
    const answer = workspaceAnswer('POST', path);
    assert.equal(answer.status, 503, path);
    assert.equal(body(answer).message, NOT_CONNECTED);
  }
  assert.match(NOT_CONNECTED, /not connected in this build yet/);
  const run = hostAnswer('POST', '/api/research/runs');
  assert.equal(run.status, 503);
  assert.equal(body(run).detail, NOT_CONNECTED);
});

test('host requests: the research list is empty, memory is off, the rest of /api is left alone', () => {
  assert.deepEqual(body(hostAnswer('GET', '/api/research/library')), { items: [] });
  assert.deepEqual(body(hostAnswer('GET', '/api/research/dr2/settings')), {});
  assert.equal(hostAnswer('GET', '/api/memory/activity').status, 404);
  assert.equal(hostAnswer('GET', '/api/companies'), null);         // Reports' own requests: no backend
  assert.equal(hostAnswer('GET', '/api/report/status/abc'), null);
});

function call(middleware, method, url) {
  return new Promise((resolve) => {
    const res = { headers: {}, statusCode: 0, setHeader(k, v) { this.headers[k] = v; }, end(data) { resolve({ status: this.statusCode, type: this.headers['Content-Type'], data: String(data ?? '') }); } };
    middleware({ method, url }, res, () => resolve({ passed: true }));
  });
}

test('middleware: readiness, the client page for its own routes, files and other paths passed on', async () => {
  const serve = workspaceMiddleware(`${root}public/xyz`);
  const ready = await call(serve, 'GET', '/api/xyz/status');
  assert.deepEqual(JSON.parse(ready.data), { ready: true });
  const page = await call(serve, 'GET', '/xyz/c/new?x=1');
  assert.equal(page.status, 200);
  assert.match(page.type, /^text\/html/);
  assert.match(page.data, /<base href="\/xyz\/" \/>/);
  assert.equal(JSON.parse((await call(serve, 'GET', '/xyz/api/user')).data).name, 'Guest');
  const asset = readdirSync(`${root}public/xyz/assets`).find((name) => /^index\..+\.js$/.test(name));
  assert.deepEqual(await call(serve, 'GET', `/xyz/assets/${asset}`), { passed: true });      // a real file
  assert.deepEqual(await call(serve, 'GET', '/src/main.jsx'), { passed: true });
  assert.deepEqual(await call(serve, 'GET', '/api/companies'), { passed: true });
  assert.deepEqual(await call(serve, 'GET', '/xyz/../package.json'), { passed: true });      // never outside the client
});

test('the copied client is adapted to this build: base path, Callisto, navy, no service worker', () => {
  const page = read('public/xyz/index.html');
  assert.match(page, /<base href="\/xyz\/" \/>/);
  assert.match(page, /<title>Callisto<\/title>/);
  // no Deep Research in this build (owner 2026-11-22): its switch is hidden, its shortcut is taken back
  assert.match(page, /<style id="callisto-query-only">[\s\S]*\[data-research-toggle\][^{]*\{ display: none !important; \}/);
  assert.match(page, /<script id="callisto-query-only-guard">/);
  assert.match(page, /<style id="callisto-build">/);
  assert.match(page, /--surface-primary: 14 20 32 !important/);
  assert.doesNotMatch(page, /registerSW|rel="manifest"/);
  assert.equal(existsSync(`${root}public/xyz/sw.js`), false);
  const assets = `${root}public/xyz/assets`;
  const main = readdirSync(assets).find((name) => /^index\..+\.js$/.test(name) && readFileSync(`${assets}/${name}`, 'utf8').includes('com_ui_indago_panel_search'));
  const js = readFileSync(`${assets}/${main}`, 'utf8');
  assert.match(js, /com_ui_indago:`Callisto`/);
  assert.match(js, /com_ui_indago_panel_nav_query:`Reports`/);
  // the question box's hint (owner 2026-11-22)
  assert.match(js, /com_ui_indago_placeholder_query:`Ask Callisto`/);
  assert.match(js, /-7\.625 58 719 64/);
  const sentences = [...js.matchAll(/com_[a-z0-9_]+:(`(?:[^`\\]|\\.)*`)/g)].map((m) => m[1]);
  assert.equal(sentences.filter((text) => text.includes('Indago')).length, 0, 'no sentence says Indago');
  // US only: no sentence names the Japanese filing system, clock or market data
  assert.deepEqual(sentences.filter((text) => /Japan|Tokyo|TSE\b|EDINET|J-Quants|JPX|TDnet|\byen\b|¥|\bJST\b|TOPIX|Nikkei/.test(text)), []);
  assert.match(js, /com_ui_indago_filings_source:`SEC EDGAR`/);
  const panel = readdirSync(assets).find((name) => /^DeepResearchPanel\..+\.js$/.test(name));
  assert.match(readFileSync(`${assets}/${panel}`, 'utf8'), /query:`\/#\/Reports`/);
});

test('the dev and preview servers use the stand-in; the page falls back when it is absent', () => {
  const config = read('vite.config.js');
  assert.match(config, /import uiOnlyWorkspace from '\.\/dev\/uiOnlyWorkspace\.js'/);
  assert.match(config, /plugins: \[react\(\), uiOnlyWorkspace\(\)\]/);
  // with BACKEND_ORIGIN set, the report routes and /api reach the backend; without it nothing is proxied
  assert.match(config, /'\/api': \{ target: backendOrigin, changeOrigin: true \},/);
  assert.match(config, /'\^\/\(start\|status\|jobs\|download\)\(\/\|\\\\\?\|\$\)': \{ target: backendOrigin, changeOrigin: true \},/);
  assert.match(config, /\.\.\.\(backendOrigin \? \{[\s\S]*?\} : \{\}\),/);
  // the chat and the price card's history go to the Callisto research desk bridge, ahead of /api
  assert.match(config, /const callistoOrigin = env\.CALLISTO_ORIGIN \|\| 'http:\/\/127\.0\.0\.1:8140'/);
  assert.ok(config.indexOf("'/xyz/api/agents/chat': callistoProxy") < config.indexOf("'/api': { target: backendOrigin"));
  const plugin = read('dev/uiOnlyWorkspace.js');
  assert.match(plugin, /configureServer\(server\)/);
  assert.match(plugin, /configurePreviewServer\(server\)/);
  // without the stand-in (plain static hosting) the status check fails and the page shows its own landing
  assert.match(read('src/pages/DeepResearch.jsx'), /if \(verdict === 'offline'\) \{ setPhase\('offline'\); return; \}/);
  assert.match(read('src/Layout.jsx'), /externalTrigger=\{EMBED_PATHS\.has\(path\)\}/);
});

test('bridge: a question and its stream reach the research desk while it is up, "not connected" when down', async () => {
  assert.equal(bridgeTarget({ '/xyz/api/agents/chat': { target: 'http://127.0.0.1:8140' } }), 'http://127.0.0.1:8140');
  assert.equal(bridgeTarget(undefined), null);
  assert.equal(isBridgeRequest('/xyz/api/agents/chat/Indago'), true);
  assert.equal(isBridgeRequest('/xyz/api/agents/chat/stream/abc'), true);
  assert.equal(isBridgeRequest('/xyz/api/agents/chat/active'), false);       // the job list stays a start-up answer
  assert.equal(isBridgeRequest('/xyz/api/messages/abc', 'GET'), true);         // an answered chat reads back its messages
  assert.equal(isBridgeRequest('/xyz/api/convos', 'GET'), true);
  assert.equal(isBridgeRequest('/xyz/api/convos/update', 'POST'), false);
  const root = `${fileURLToPath(new URL('../', import.meta.url))}public/xyz`;
  const up = workspaceMiddleware(root, { bridgeUp: async () => true });
  assert.deepEqual(await call(up, 'POST', '/xyz/api/agents/chat/Indago'), { passed: true });
  assert.deepEqual(await call(up, 'GET', '/xyz/api/agents/chat/stream/abc'), { passed: true });
  assert.deepEqual(JSON.parse((await call(up, 'GET', '/xyz/api/agents/chat/active')).data), { activeJobIds: [] });
  const down = workspaceMiddleware(root, { bridgeUp: async () => false });
  const refused = await call(down, 'POST', '/xyz/api/agents/chat/Indago');
  assert.equal(refused.status, 503);
  assert.equal(JSON.parse(refused.data).message, NOT_CONNECTED);
  const none = await call(workspaceMiddleware(root), 'POST', '/xyz/api/agents/chat/Indago');
  assert.equal(none.status, 503);                                              // no bridge configured
  let calls = 0;
  const probe = bridgeProbe('http://127.0.0.1:9', { fetchImpl: async () => { calls += 1; return { ok: true }; } });
  assert.equal(await probe(), true);
  assert.equal(await probe(), true);
  assert.equal(calls, 1);                                                      // cached between questions
  const dead = bridgeProbe('http://127.0.0.1:9', { fetchImpl: async () => { throw new Error('refused'); } });
  assert.equal(await dead(), false);
});

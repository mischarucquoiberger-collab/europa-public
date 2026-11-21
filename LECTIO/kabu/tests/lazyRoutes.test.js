import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { PassThrough } from 'node:stream';
import React from 'react';
import { renderToPipeableStream } from 'react-dom/server';
import { build } from 'esbuild';

const require = createRequire(import.meta.url);
const root = fileURLToPath(new URL('../', import.meta.url));
// Compile the REAL App/registry/Layout, substituting only leaf page bodies and
// external effects. React and Router stay real. No DOM package or API required.
async function appHarness() {
  const fragment = 'import React from "react"; export default function Stub({children}) { return React.createElement(React.Fragment,null,children); }';
  const stubs = {
    '@/lib/useIsPhone': 'export default ()=>globalThis.__routeFixture.phone;',
    '@/components/MobileGate': 'import React from "react"; export default ({pageName})=>React.createElement("aside",null,"Desktop required: "+pageName);',
    '@/components/IndagoLoader': 'import React from "react"; export default ({label})=>React.createElement("span",null,label);',
    '@/components/ui/toaster': 'export const Toaster=()=>null;',
    '@/components/CircleTransition': 'export const CircleTransitionProvider=({children})=>children;',
    './lib/PageNotFound': 'import React from "react";export default ()=>React.createElement("p",null,"Not found");',
    'react-router-dom': `import React from "react";import {MemoryRouter} from ${JSON.stringify(require.resolve('react-router-dom'))};export * from ${JSON.stringify(require.resolve('react-router-dom'))};export const HashRouter=({children})=>React.createElement(MemoryRouter,{initialEntries:[globalThis.__routeFixture.route]},children);`,
  };
  const output = await build({ entryPoints: [root + 'src/App.jsx'], bundle: true, write: false, platform: 'node', format: 'cjs', jsx: 'automatic',
    external: ['react', 'react/*', require.resolve('react-router-dom')], logLevel: 'silent', plugins: [{ name: 'offline-leaves', setup(builder) {
      builder.onResolve({ filter: /.*/ }, args => {
        if (args.path in stubs) return { path: args.path, namespace: 'stub' };
        if (args.importer.endsWith('pages.config.js') && args.kind === 'dynamic-import') return { path: args.path, namespace: 'page' };
        if (args.path === '@/components/RouteBoundary') return { path: root + 'src/components/RouteBoundary.jsx' };
        if (args.path.startsWith('@/')) return { path: args.path, namespace: 'stub' };
      });
      builder.onLoad({ filter: /.*/, namespace: 'stub' }, args => ({ contents: stubs[args.path] || fragment, loader: 'jsx', resolveDir: root }));
      builder.onLoad({ filter: /.*/, namespace: 'page' }, args => ({ contents:
        `import React from 'react';import {useLocation} from 'react-router-dom';globalThis.__routeFixture.loaded.push(${JSON.stringify(args.path)});export default function Page(){const location=useLocation();return React.createElement('section',null,${JSON.stringify(args.path)}+location.search);}`, loader: 'jsx', resolveDir: root }));
    } }] });
  const module = { exports: {} };
  new Function('require', 'module', 'exports', output.outputFiles[0].text)(require, module, module.exports);
  return module.exports.default;
}

async function renderFixture(route, { phone = false } = {}) {
  globalThis.__routeFixture = { route, phone, loaded: [] };
  globalThis.localStorage = { getItem: () => null };
  globalThis.sessionStorage = { setItem() {} };
  const App = await appHarness();
  const body = new PassThrough();
  const chunks = [];
  body.on('data', chunk => chunks.push(chunk));
  const done = new Promise((resolve, reject) => { body.on('end', resolve); body.on('error', reject); });
  const stream = renderToPipeableStream(React.createElement(App), {
    onAllReady() { stream.pipe(body); }, onError(error) { body.destroy(error); },
  });
  await done;
  return { html: Buffer.concat(chunks).toString(), loaded: [...globalThis.__routeFixture.loaded] };
}

// The app is Home, Reports (with its report builder and viewer) and Deep Research.
for (const [route, expected] of [['/Home', './pages/LectioHome'], ['/Reports', './pages/Home'],
  ['/GenerateReport?ticker=7203&mode=full', './pages/GenerateReport'], ['/Viewer', './pages/ReportViewer'], ['/DeepResearch', './pages/DeepResearch']]) {
  test(`route ${route} loads only its selected module and retains URL parameters`, async () => {
    const result = await renderFixture(route);
    assert.deepEqual(result.loaded, [expected]);
    assert.ok(result.html.includes(expected));
    if (route.includes('?')) assert.ok(result.html.includes('?ticker=7203&amp;mode=full'));
  });
}

test('the registry holds exactly the five pages, each loaded only when its route renders', () => {
  const cfg = readFileSync(new URL('../src/pages.config.js', import.meta.url), 'utf8');
  const keys = [...cfg.matchAll(/^\s*"([A-Za-z][A-Za-z0-9-]*)":\s*[A-Za-z][A-Za-z0-9]*,?/gm)].map(m => m[1]);
  assert.deepEqual(keys, ['Home', 'Reports', 'GenerateReport', 'Viewer', 'DeepResearch']);
  assert.equal((cfg.match(/= lazy\(\(\) => import\('\.\/pages\//g) || []).length, 5);
  assert.match(cfg, /mainPage: "Home",/);
});

// "/" redirects to Home. Server rendering cannot run the navigation effect, so
// the harness proves the redirect is matched and no page module loads for it.
test('/ redirects to Home without loading a page or showing the 404', async () => {
  const result = await renderFixture('/');
  assert.deepEqual(result.loaded, []);
  assert.doesNotMatch(result.html, /Not found|Desktop required/);
  const app = readFileSync(new URL('../src/App.jsx', import.meta.url), 'utf8');
  assert.match(app, /<Route path="\/" element=\{<Navigate to=\{HOME_ROUTE\} replace \/>\} \/>/);
  assert.ok(app.indexOf('Object.entries(Pages).map') < app.indexOf('<Route path="*"'), 'pages are matched before the not-found route');
});

test('there is no sign-in and no other section: their old addresses are plain 404s', async () => {
  for (const route of ['/Auth', '/sign-up', '/forgot-password', '/accept-invite', '/account', '/operator',
    '/Query', '/ScreenerMode', '/CompanyProfile?code=7203', '/Activist', '/NewsScreener', '/API', '/Missing']) {
    const result = await renderFixture(route);
    assert.deepEqual(result.loaded, [], route);
    assert.match(result.html, /Not found/, route);
  }
  const app = readFileSync(new URL('../src/App.jsx', import.meta.url), 'utf8');
  assert.doesNotMatch(app, /Auth|Clerk|session|ProtectedRoute|isAuthenticated/i, 'the shell has no access gate');
});

for (const route of ['/Reports', '/GenerateReport?ticker=7203&mode=full', '/Viewer']) {
  test(`phone gate for ${route} never imports or renders its heavy page`, async () => {
    const result = await renderFixture(route, { phone: true });
    assert.deepEqual(result.loaded, []);
    assert.match(result.html, /Desktop required/);
  });
}

test('phone keeps Home and Deep Research available; unknown routes preserve not-found behavior', async () => {
  for (const route of ['/Home', '/DeepResearch']) assert.equal((await renderFixture(route, { phone: true })).loaded.length, 1, route);
  const unknown = await renderFixture('/Missing', { phone: true });
  assert.deepEqual(unknown.loaded, []);
  assert.match(unknown.html, /Not found/);
});

test('test script discovers every node test, including future additions', () => {
  const pkg = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'));
  assert.equal(pkg.scripts.test, 'node --test tests/*.test.js');
});

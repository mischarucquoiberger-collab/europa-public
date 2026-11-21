// An unknown address PATH (e.g. /no-such-page-xyz, served by the server
// catch-all) shows the 404 page instead of silently opening Home. The app routes
// by hash, so only "/" and "/index.html" are the shell's own paths.
import test from 'node:test';
import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import React from 'react';
import { renderToString } from 'react-dom/server';
import { build } from 'esbuild';

const require = createRequire(import.meta.url);
const root = fileURLToPath(new URL('../', import.meta.url));
const routerPath = require.resolve('react-router-dom');

async function load(entry, stubs = {}) {
  const output = await build({ entryPoints: [root + entry], bundle: true, write: false, platform: 'node', format: 'cjs', jsx: 'automatic', loader: { '.css': 'empty' },
    external: ['react', 'react/*', 'react-dom', 'react-dom/*', 'react-router-dom', routerPath], logLevel: 'silent', plugins: [{ name: 'stubs', setup(b) {
      b.onResolve({ filter: /.*/ }, (args) => {
        if (args.path in stubs) return { path: args.path, namespace: 'stub' };
        if (stubs['*'] && args.path.startsWith('@/')) return { path: args.path, namespace: 'stub' };
      });
      b.onLoad({ filter: /.*/, namespace: 'stub' }, (args) => ({ contents: stubs[args.path] ?? stubs['*'], loader: 'jsx', resolveDir: root }));
    } }] });
  const module = { exports: {} };
  new Function('require', 'module', 'exports', output.outputFiles[0].text)(require, module, module.exports);
  return module.exports;
}

const fragment = 'import React from "react"; export default function Stub({children}) { return React.createElement(React.Fragment,null,children); }';
const appStubs = {
  '*': fragment,
  '@/components/ui/toaster': 'export const Toaster=()=>null;',
  '@/components/CircleTransition': 'export const CircleTransitionProvider=({children})=>children;',
  './pages.config': 'import React from "react"; export const pagesConfig={Pages:{Home:()=>React.createElement("section",null,"HOME PAGE")},Layout:({children})=>children,mainPage:"Home"};',
  'react-router-dom': `import React from "react";import {MemoryRouter} from ${JSON.stringify(routerPath)};export * from ${JSON.stringify(routerPath)};export const HashRouter=({children})=>React.createElement(MemoryRouter,{initialEntries:[globalThis.__hashRoute || "/"]},children);`,
  './lib/PageNotFound': 'import React from "react"; export default ({serverPath})=>React.createElement("p",null,"NOT FOUND "+String(serverPath));',
};

function renderAt(App, pathname) {
  const had = 'window' in globalThis;
  globalThis.window = { location: { pathname, hash: '' } };
  try { return renderToString(React.createElement(App)); } finally { if (!had) delete globalThis.window; }
}

test('isUnknownShellPath: only the shell\'s own paths are known', async () => {
  const { isUnknownShellPath } = await load('src/App.jsx', appStubs);
  for (const p of ['/', '', '/index.html', undefined]) assert.equal(isUnknownShellPath(p), false, String(p));
  for (const p of ['/no-such-page-xyz', '/Home', '/a/b', '/index.htm', '/%E6%A0%AA']) assert.equal(isUnknownShellPath(p), true, p);
});

test('App: an unknown address path renders the 404, "/" opens the app on Home', async () => {
  const { default: App } = await load('src/App.jsx', appStubs);
  const miss = renderAt(App, '/no-such-page-xyz');
  assert.match(miss, /NOT FOUND \/no-such-page-xyz/);
  assert.doesNotMatch(miss, /HOME PAGE/);
  // "/" (hash "" or "#/") redirects to #/Home; server rendering cannot run the
  // navigation, so the redirect is matched (no 404) and #/Home itself renders the page.
  const root = renderAt(App, '/');
  assert.doesNotMatch(root, /NOT FOUND/);
  globalThis.__hashRoute = '/Home';
  try {
    const home = renderAt(App, '/');
    assert.doesNotMatch(home, /NOT FOUND/);
    assert.match(home, /HOME PAGE/);
  } finally { delete globalThis.__hashRoute; }
  const app = readFileSync(new URL('../src/App.jsx', import.meta.url), 'utf8');
  assert.match(app, /<Route path="\/" element=\{<Navigate to=\{HOME_ROUTE\} replace \/>\} \/>/);
});

test('PageNotFound: a server path is shown and Home is a full /#/Home link; hash 404s keep the router link', async () => {
  const { default: PageNotFound } = await load('src/lib/PageNotFound.jsx');
  const { MemoryRouter } = require(routerPath);
  const at = (route, props) => renderToString(React.createElement(MemoryRouter, { initialEntries: [route] }, React.createElement(PageNotFound, props)));
  const server = at('/', { serverPath: '/no-such-page-xyz' });
  assert.match(server, /There is no page at/);
  assert.match(server, /no-such-page-xyz/);
  assert.match(server, /href="\/#\/Home"[^>]*>Go to Home</);
  const hash = at('/this-does-not-exist');
  assert.match(hash, /this-does-not-exist/);
  assert.match(hash, /href="\/Home"[^>]*>Go to Home</);
  // same look on both
  const cls = (html) => html.match(/<a [^>]*class="([^"]+)"/)[1];
  assert.equal(cls(server), cls(hash));
});

test('PageNotFound: no Tokyo status line; the Error 404 eyebrow sits right above the centred title (owner 2026-10-13)', async () => {
  const { default: PageNotFound } = await load('src/lib/PageNotFound.jsx');
  const { MemoryRouter } = require(routerPath);
  const html = renderToString(React.createElement(MemoryRouter, { initialEntries: ['/x'] }, React.createElement(PageNotFound)));
  assert.doesNotMatch(html, /nf-status|sl-dot|Tokyo <time/);
  assert.match(html, /<div class="w-full max-w-md min-w-0 text-center"><p class="[^"]*">Error 404<\/p><h1 class="mt-3 text-3xl font-semibold tracking-tight">Page not found<\/h1>/);
});

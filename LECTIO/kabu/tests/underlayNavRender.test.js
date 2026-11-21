// The REAL Dashboard menu, server-rendered: one Deep Research row, every row a
// working link to a registered page (no dead rows; the one "Soon" row, API,
// opens its own page), no raw route paths beside the labels, and the current
// page marked.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { build } from 'esbuild';

const require = createRequire(import.meta.url);
const root = fileURLToPath(new URL('../', import.meta.url));

async function menuHarness() {
  const stubs = {
    '@/lib/bodyScrollLock': 'export const acquireBodyScrollLock=()=>()=>{};',
    // animation only runs in effects, which server rendering never executes;
    // the module itself registers CustomEase and creates the "energy" ease
    'gsap': 'export default {registerPlugin(){}};',
    'gsap/CustomEase': 'export const CustomEase={create(){}};',
  };
  const output = await build({
    stdin: { contents: `import React from "react";import {MemoryRouter} from "react-router-dom";import UnderlayNav from "./src/components/UnderlayNav.jsx";
      export default function Menu({route}){return React.createElement(MemoryRouter,{initialEntries:[route]},React.createElement(UnderlayNav,{externalTrigger:route==="/DeepResearch"}));}`,
    resolveDir: root, loader: 'jsx' },
    bundle: true, write: false, platform: 'node', format: 'cjs', jsx: 'automatic',
    external: ['react', 'react/*', 'react-dom', 'react-dom/*', 'react-router-dom'], logLevel: 'silent',
    plugins: [{ name: 'stubs', setup(builder) {
      builder.onResolve({ filter: /.*/ }, args => (args.path in stubs ? { path: args.path, namespace: 'stub' } : undefined));
      builder.onLoad({ filter: /.*/, namespace: 'stub' }, args => ({ contents: stubs[args.path], loader: 'js' }));
    } }],
  });
  const module = { exports: {} };
  new Function('require', 'module', 'exports', output.outputFiles[0].text)(require, module, module.exports);
  return module.exports.default;
}

const Menu = await menuHarness();
const render = route => renderToStaticMarkup(React.createElement(Menu, { route }));
const rows = html => [...html.matchAll(/<a href="#(\/[A-Za-z]+)"[^>]*class="underlay-nav__link-large[^"]*"[^>]*><span class="underlay-nav__link-label">([^<]+)<\/span>(<span class="underlay-nav__link-soon" aria-hidden="true">Soon<\/span>)?<\/a>/g)]
  .map(m => ({ route: m[1], label: m[2], soon: Boolean(m[3]) }));

// The product is Home, Reports and Callisto (the Deep Research page, named after the moon).
test('menu renders Home, Reports and Callisto only, all working links; no Soon row', () => {
  const html = render('/Home');
  const items = rows(html);
  assert.deepEqual(items.map(i => i.label), ['Home', 'Reports', 'Callisto']);
  assert.deepEqual(items.filter(i => i.soon), []);
  const cfg = readFileSync(new URL('../src/pages.config.js', import.meta.url), 'utf8');
  for (const { route } of items) assert.match(cfg, new RegExp(`"${route.slice(1)}":`), `${route} is a registered page`);
  // No row is relabelled and no badge is drawn.
  assert.equal((html.match(/<a [^>]*aria-label=/g) || []).length, 0);
  assert.equal((html.match(/class="underlay-nav__link-soon"/g) || []).length, 0);
  assert.doesNotMatch(html, /href="#\/(Query|Activist|NewsScreener|ScreenerMode|API)"/);
  assert.doesNotMatch(html, /aria-disabled="true"|is--soon|Coming soon|Signal Feed|>Satellite<|>XYZ<|Deep Research 2\.0|underlay-nav__route-hint/);
});

test('the current page is marked; a page without a row marks none', () => {
  assert.doesNotMatch(render('/Query'), /aria-current="page"/);
  for (const [route, label] of [['/Home', 'Home'], ['/', 'Home'], ['/Reports', 'Reports'], ['/DeepResearch', 'Callisto']]) {
    const html = render(route);
    const current = [...html.matchAll(/<a href="#\/[A-Za-z]+" aria-current="page"[^>]*><span class="underlay-nav__link-label">([^<]+)</g)].map(m => m[1]);
    assert.deepEqual(current, [label], route);
  }
  // Deep Research embeds a workspace with its own Dashboard link: the header steps aside there only
  assert.match(render('/Home'), /^<div class="underlay-nav-root">/);
  assert.match(render('/DeepResearch'), /^<div class="underlay-nav-root underlay-nav-root--external">/);
});

// Owner 2026-10-13: the pill sat 1.5 rows low over a scrolled dark Home, and
// the white logo vanished under the resource's multiply blend on dark pages.
test('pill measures open rows from live rects and re-checks after settling', async () => {
  const { readFileSync } = await import('node:fs');
  const src = readFileSync(new URL('../src/components/UnderlayNav.jsx', import.meta.url), 'utf8');
  assert.match(src, /const measureRow = \(link\) =>/);
  assert.match(src, /linkRect\.top - listRect\.top/);
  assert.match(src, /eventCallback\?\.\("onComplete", verify\)/);
  assert.match(src, /pillSettleTimer = setTimeout/);
  assert.match(src, /\.underlay-nav \.underlay-nav__logo \{\n  width: auto;\n  mix-blend-mode: normal;\n/);
});

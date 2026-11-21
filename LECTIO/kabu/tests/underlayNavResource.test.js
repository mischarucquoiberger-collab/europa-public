// The Dashboard IS the Osmo Supply "Fixed Underlay Navigation" resource, 1:1.
// These tests pin the three things that must stay the resource's own:
//   1. markup: its skeleton (elements, classes, data- attributes, order), with
//      Indago content only in the logo slot, the rows and the bottom columns,
//      plus the Indago pieces the owner kept: the magnetic orange hover pill
//      (an aria-hidden li in the row list; it glides, the names no longer
//      decode, owner 2026-10-13) and the Account section (plain small lines);
//   2. CSS: every resource rule, values and order unchanged, scoped under
//      .underlay-nav, and the Indago host/integration rules limited to a
//      reviewed list (no z-index lift, masks, keyframes or other extras);
//   3. JS: the resource's GSAP calls (initial sets, one timeline split by
//      addPause, easeReverse, CustomEase "energy") and its four-branch toggle,
//      overlay click, Escape and resize, against a recording GSAP and a fake DOM.
// The real component is bundled with esbuild (node has no DOM).
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { build } from 'esbuild';

const require = createRequire(import.meta.url);
const root = fileURLToPath(new URL('../', import.meta.url));

async function bundle(stubs, contents) {
  const output = await build({
    stdin: { contents, resolveDir: root, loader: 'jsx' },
    bundle: true, write: false, platform: 'node', format: 'cjs', jsx: 'automatic',
    external: ['react', 'react/*', 'react-dom', 'react-dom/*', 'react-router-dom'], logLevel: 'silent',
    plugins: [{ name: 'stubs', setup(builder) {
      builder.onResolve({ filter: /.*/ }, args => (args.path in stubs ? { path: args.path, namespace: 'stub' } : undefined));
      builder.onLoad({ filter: /.*/, namespace: 'stub' }, args => ({ contents: stubs[args.path], loader: 'js' }));
    } }],
  });
  const module = { exports: {} };
  new Function('require', 'module', 'exports', output.outputFiles[0].text)(require, module, module.exports);
  return module.exports;
}

/* ── 1. markup ─────────────────────────────────────────────────────────── */

const ui = await bundle({
  '@/lib/bodyScrollLock': 'export const acquireBodyScrollLock=()=>()=>{};',
  'gsap': 'export default {registerPlugin(){}};',
  'gsap/CustomEase': 'export const CustomEase={create(){}};',
}, `import React from "react";import {MemoryRouter} from "react-router-dom";import UnderlayNav, {UNDERLAY_NAV_CSS} from "./src/components/UnderlayNav.jsx";
  export {UNDERLAY_NAV_CSS};
  export default function Menu({route}){return React.createElement(MemoryRouter,{initialEntries:[route]},React.createElement(UnderlayNav,{externalTrigger:route==="/DeepResearch"}));}`);

function render(route) {
  return renderToStaticMarkup(React.createElement(ui.default, { route }));
}

/** Element skeleton of the rendered nav: one line per element, indented by
 *  depth, as tag + resource classes + data- attributes. */
function skeleton(html) {
  const body = html.replace(/<style>[\s\S]*?<\/style>/, '');
  const lines = [];
  let depth = 0;
  for (const m of body.matchAll(/<(\/?)([a-z0-9]+)([^>]*)>/g)) {
    const [, closing, tag, attrs] = m;
    if (closing) { depth--; continue; }
    const cls = (attrs.match(/class="([^"]*)"/)?.[1] || '').split(' ').filter(Boolean).map(c => '.' + c).join('');
    const data = [...attrs.matchAll(/(data-[a-z-]+)=/g)].map(d => `[${d[1]}]`).join('');
    lines.push('  '.repeat(depth) + tag + cls + data);
    if (!attrs.endsWith('/')) depth++;      // a void element (<img ... />) opens no level
  }
  return lines;
}

const row = (current) => [
  '        li[data-reveal-l]',
  `          a.underlay-nav__link-large.w-inline-block${current ? '.w--current' : ''}`,
  '            span.underlay-nav__link-label',
];
const expectedSkeleton = () => [
  'div.underlay-nav-root',
  '  div.underlay-nav',
  '    header.underlay-nav__header',
  '      div.underlay-nav__bar',
  '        div.underlay-nav__container',
  '          a.underlay-nav__logo.indago-wordmark',
  // the planet (LogoPlanet), waiting below until it comes up
  '            span.underlay-nav__logo-planet.is--below',
  '              canvas.underlay-nav__logo-planet-canvas',
  '            svg.underlay-nav__logo-word',
  ...Array(6).fill('              path'),
  '            span.underlay-nav__toggle-sr',
  '          button.underlay-nav__toggle[data-underlay-nav-toggle]',
  '            span.underlay-nav__toggle-text',
  '              span.underlay-nav__toggle-label',
  '                svg.underlay-nav__toggle-word',
  ...Array(9).fill('                  path'),
  '                span.underlay-nav__toggle-sr',
  '              span.underlay-nav__toggle-label',
  '                svg.underlay-nav__toggle-word',
  ...Array(5).fill('                  path'),
  '                span.underlay-nav__toggle-sr',
  '            span.underlay-nav__toggle-icon',
  '              span.underlay-nav__toggle-bar',
  '              span.underlay-nav__toggle-bar',
  '    nav.underlay-nav__menu[data-underlay-nav-menu]',
  '      div.underlay-nav__inner',
  '        ul.underlay-nav__list',
  '          li.underlay-nav__hover-pill',
  '            div.underlay-nav__pill-clone',
  // Three rows (Home, Reports, Callisto), none marked Soon.
  ...[0, 1, 2].flatMap(() => ['              div.underlay-nav__pill-row', '                span.underlay-nav__pill-link.w-inline-block', '                  span.underlay-nav__pill-label']),
  ...[...row(true), ...row(), ...row()].map(l => '  ' + l),
  '        div.underlay-nav__bottom',
  '          div.underlay-nav__bottom-col',
  '            div[data-reveal-s]',
  '              span.underlay-nav__link-small.is--faded',
  '          div.underlay-nav__bottom-border',
  '    div.underlay-nav__overlay[data-underlay-nav-overlay]',
  '      div.underlay-nav__dark',
  '      div.underlay-nav__borders',
  '        div.underlay-nav__border-row',
  '          div.underlay-nav__border',
  '          div.underlay-nav__corner',
  '        div.underlay-nav__border-row',
  '          div.underlay-nav__corner.is--bottom',
  '          div.underlay-nav__border',
];

test('markup: the resource skeleton, every class and data- attribute in its place', () => {
  assert.deepEqual(skeleton(render('/Home')), expectedSkeleton());
});

test('markup: Indago content replaces only the demo content', () => {
  const html = render('/Home');
  // logo slot: the decorative planet, then the Indago wordmark, linked Home, named inside the svg
  assert.match(html, /<a href="#\/Home" class="underlay-nav__logo indago-wordmark"><span class="underlay-nav__logo-planet is--below" aria-hidden="true"><canvas class="underlay-nav__logo-planet-canvas"><\/canvas><\/span><svg class="underlay-nav__logo-word" viewBox="[^"]+ 58 [\d.]+ 64" style="--ul-w:[\d.]+"[^>]*>(?:<path [^>]*><\/path>){6}<\/svg><span class="underlay-nav__toggle-sr">Europa<\/span><\/a>/);
  // toggle: resource attributes and structure; Indago's name for the menu
  assert.match(html, /<button data-underlay-nav-toggle="true" aria-expanded="false" aria-label="open menu" class="underlay-nav__toggle" type="button"><span class="underlay-nav__toggle-text"><span class="underlay-nav__toggle-label"><svg class="underlay-nav__toggle-word" viewBox="[^"]+ 58 [\d.]+ 64" style="--ul-w:[\d.]+" fill="currentColor" stroke="currentColor" stroke-width="3" stroke-linejoin="round" aria-hidden="true" focusable="false">(<path [^>]*><\/path>){9}<\/svg><span class="underlay-nav__toggle-sr">Dashboard<\/span><\/span><span class="underlay-nav__toggle-label"><svg class="underlay-nav__toggle-word" [^>]*aria-hidden="true"[^>]*>(<path [^>]*><\/path>){5}<\/svg><span class="underlay-nav__toggle-sr">Close<\/span><\/span><\/span>/);
  assert.match(html, /<nav data-underlay-nav-menu="true" class="underlay-nav__menu" role="dialog" aria-modal="true" aria-label="Dashboard navigation" aria-hidden="true">/);
  const labels = [...html.matchAll(/<span class="underlay-nav__link-label">([^<]+)<\/span>/g)].map(m => m[1]);
  assert.deepEqual(labels, ['Home', 'Reports', 'Callisto']);
  const small = [...html.matchAll(/class="underlay-nav__link-small( is--faded)?( underlay-nav__link-button)?"[^>]*>([^<]+)</g)].map(m => (m[1] ? '(faded) ' : '') + m[3]);
  // The bottom holds one line: the credit (owner 2026-11-22). No legal links, no buttons.
  assert.deepEqual(small, ['(faded) Made by the Europa team in room 323']);
  assert.equal((html.match(/underlay-nav__link-button|Quick Links|Privacy|Terms/g) || []).length, 0);
  assert.doesNotMatch(html, /href="#"|↗/);
  assert.doesNotMatch(html, /account|Sign out|Operator|href="#\/account"/i);
  // the pill: one aria-hidden li, first in the row list
  assert.match(html, /<ul class="underlay-nav__list"><li class="underlay-nav__hover-pill" aria-hidden="true"><div class="underlay-nav__pill-clone" inert=""><div class="underlay-nav__pill-row"><span class="underlay-nav__pill-link w-inline-block"><span class="underlay-nav__pill-label">Home<\/span><\/span><\/div>/);
  assert.match(html, /<span class="underlay-nav__pill-label">Callisto<\/span><\/span><\/div><\/div><\/li><li data-reveal-l="true">/);
  assert.match(html, /<div data-underlay-nav-overlay="" class="underlay-nav__overlay">/);
  // no other elements from the old Dashboard
  assert.doesNotMatch(html, /route-hint/);
});

/* ── 2. CSS ────────────────────────────────────────────────────────────── */

// resource.css as purchased (Osmo Supply, Fixed Underlay Navigation).
const RESOURCE_CSS = `
:root { --menu-width: 30em; }
a { color: inherit; text-decoration: none; }
.underlay-nav__header { z-index: 100; color: #fff; position: fixed; inset: 0% 0% auto; }
.underlay-nav__bar { width: 100%; margin-left: auto; margin-right: auto; }
.underlay-nav__container { justify-content: space-between; align-items: center; padding: 2.5em; display: flex; }
.underlay-nav__logo { mix-blend-mode: multiply; justify-content: center; align-items: center; width: 6.875em; display: flex; }
.underlay-nav__logo-svg { width: 100%; }
.underlay-nav__toggle { grid-column-gap: .75em; grid-row-gap: .75em; outline-offset: 0px; background-color: #0000; border: 1px #000; outline: 3px #555; justify-content: center; align-items: center; margin: -1em; padding: 1em; display: flex; font: inherit; color: #fff; cursor: pointer; }
.underlay-nav__toggle-text { flex-flow: column; flex: none; justify-content: flex-start; align-items: flex-end; height: 1.5em; display: flex; overflow: hidden; }
.underlay-nav__toggle-label { font-size: 1.25em; }
.underlay-nav__toggle-icon { grid-column-gap: .375em; grid-row-gap: .375em; flex-flow: column; flex: none; justify-content: center; align-items: center; width: 1.5em; margin-bottom: -.3em; display: flex; }
.underlay-nav__toggle-bar { background-color: currentColor; flex: none; width: 100%; height: .125em; padding: 0; }
.underlay-nav__menu { z-index: 1; width: var(--menu-width); position: fixed; top: 0; bottom: 0; right: 0; }
.underlay-nav__overlay { z-index: 100; pointer-events: none; cursor: pointer; visibility: hidden; position: fixed; inset: 0% -1px 0% 0%; overflow: clip; }
.underlay-nav__inner { grid-column-gap: 2em; grid-row-gap: 2em; flex-flow: column; justify-content: space-between; align-items: stretch; width: 100%; height: 100%; padding: 7.5em 2em 2em; display: flex; overflow: auto; }
.underlay-nav__list { flex-flow: column; width: 100%; margin: 0; padding: 0; list-style: none; display: flex; }
.underlay-nav__list.is--small { grid-column-gap: .75em; grid-row-gap: .75em; }
.underlay-nav__link-large { border-radius: .25em; width: 100%; padding: .75em 1em; }
.underlay-nav__link-large.w--current { color: #ededed; background-color: #f85931; }
.underlay-nav__link-label { letter-spacing: -.04em; font-family: Haffer XH, Arial, sans-serif; font-size: 3.25em; line-height: .9; }
.underlay-nav__bottom { justify-content: flex-start; align-items: flex-start; width: 100%; padding-top: 1.5em; display: flex; position: relative; }
.underlay-nav__bottom-col { grid-column-gap: 1em; grid-row-gap: 1em; flex-flow: column; flex: 1; justify-content: flex-start; align-items: flex-start; display: flex; }
.underlay-nav__link-small { font-size: 1em; line-height: 1.1; }
.underlay-nav__link-small.is--faded { opacity: .5; }
.underlay-nav__corner { transform-origin: 100% 0; color: #fff; background-image: radial-gradient(circle farthest-side at 0 100%, #fff0 99%, #fff); width: 2em; height: 2em; }
.underlay-nav__corner.is--bottom { transform-origin: 100% 100%; background-image: radial-gradient(circle farthest-side at 0 0, #fff0 99%, #fff); }
.underlay-nav__dark { opacity: 0; background-color: #0000004d; position: absolute; inset: 0%; }
.underlay-nav__bottom-border { opacity: .15; transform-origin: 0%; background-color: currentColor; width: 100%; height: 1px; position: absolute; inset: 0% 0% auto; }
.underlay-nav__borders { flex-flow: column; justify-content: space-between; align-items: stretch; display: flex; position: absolute; inset: 0; }
.underlay-nav__border { background-color: #fff; width: 100%; height: 1em; }
.underlay-nav__border-row { flex-flow: column; justify-content: flex-start; align-items: flex-end; display: flex; }
@media screen and (max-width: 767px) {
  :root { --menu-width: 80vw; }
  .section-resource__h1 { font-size: 3em; }
  .underlay-nav__container { padding: 1.25em; }
  .underlay-nav__logo { width: 5em; }
  .underlay-nav__toggle-text { height: 1.25em; }
  .underlay-nav__toggle-label { font-size: 1em; }
  .underlay-nav__inner { padding: 5em 1.25em 1.25em; }
  .underlay-nav__link-label { font-size: 2em; }
  .underlay-nav__bottom { grid-column-gap: 2em; grid-row-gap: 2em; flex-flow: column; padding-left: 1em; padding-right: 1em; }
}`;

function parseCss(css) {
  const rules = [];
  const walk = (text, media) => {
    let pos = 0;
    for (;;) {
      const open = text.indexOf('{', pos);
      if (open < 0) return;
      let depth = 1, end = open + 1;
      while (depth && end < text.length) depth += text[end] === '{' ? 1 : text[end] === '}' ? -1 : 0, end++;
      const prelude = text.slice(pos, open).trim().replace(/\s+/g, ' ');
      const body = text.slice(open + 1, end - 1);
      if (prelude.startsWith('@media')) walk(body, prelude);
      else rules.push({ media, selector: prelude, decls: body.split(';').map(d => d.trim()).filter(Boolean)
        .map(d => [d.slice(0, d.indexOf(':')).trim(), d.slice(d.indexOf(':') + 1).trim().replace(/\s+/g, ' ')]) });
      pos = end;
    }
  };
  walk(css.replace(/\/\*[\s\S]*?\*\//g, ''), null);
  return rules;
}

const CSS = ui.UNDERLAY_NAV_CSS;
const section = (from, to) => CSS.slice(CSS.indexOf(from), to ? CSS.indexOf(to) : undefined);
const HOST = section('/* 1. Webflow host environment', '/* 2. Fixed Underlay Navigation');
const RESOURCE = section('/* 2. Fixed Underlay Navigation', '/* 3. Indago integration');
const INDAGO = section('/* 3. Indago integration');

test('CSS: every resource rule, in order, values unchanged, scoped under .underlay-nav', () => {
  assert.ok(HOST && RESOURCE && INDAGO && CSS.trimStart().startsWith('/* 1. Webflow host environment'), 'three sections, nothing outside them');
  const scope = s => (s === ':root' ? '.underlay-nav' : `.underlay-nav ${s}`);
  const expected = parseCss(RESOURCE_CSS)
    .filter(r => r.selector !== '.section-resource__h1')            // the demo page's heading
    .map(r => ({ ...r, selector: scope(r.selector),
      // the one deliberate departure from the resource: its orange accent is the app's navy
      decls: r.decls.map(([k, v]) => [k, v === '#f85931' ? '#0e1420' : v]) }));
  assert.deepEqual(parseCss(RESOURCE), expected);
  assert.doesNotMatch(CSS, /#f85931|#e8743b/i, 'no orange left in the menu');
});

test('CSS: the host environment is only the demo base the resource assumes', () => {
  assert.deepEqual(parseCss(HOST), [
    { media: null, selector: '@font-face', decls: [['font-family', '"Haffer XH"'], ['src', 'local("Helvetica Neue"), local("HelveticaNeue")'], ['font-weight', '400'], ['font-style', 'normal']] },
    { media: null, selector: '@font-face', decls: [['font-family', '"Haffer"'], ['src', 'local("Helvetica Neue"), local("HelveticaNeue")'], ['font-weight', '400'], ['font-style', 'normal']] },
    // live demo: body 16px at every width (no fluid scale), Haffer, line-height 1.25, ink #312e2e
    { media: null, selector: '.underlay-nav', decls: [['font-family', 'Haffer, Arial, sans-serif'], ['font-size', '16px'], ['font-weight', '400'], ['line-height', '1.25'], ['color', '#312e2e']] },
    // Webflow's Link Block class on the large links (full-width current row)
    { media: null, selector: '.underlay-nav .w-inline-block', decls: [['max-width', '100%'], ['display', 'inline-block']] },
  ]);
});

test('CSS: Indago integration rules are the reviewed list, with no invented visuals', () => {
  const got = parseCss(INDAGO).map(r => `${r.media ? r.media + ' ' : ''}${r.selector} { ${r.decls.map(d => d[0]).join(', ')} }`);
  assert.deepEqual(got, [
    '.underlay-nav .underlay-nav__header { color }',
    '.underlay-nav .underlay-nav__toggle { color }',
    'body[data-home-dark="1"] .underlay-nav .underlay-nav__header { color }',
    // owner 2026-10-13: the pop-out is always white; CLOSE takes dark ink while open
    '.underlay-nav .underlay-nav__menu { background-color }',
    'body[data-menu-status="open"] .underlay-nav .underlay-nav__toggle { color }',
    '@media screen and (min-width: 981px) .underlay-nav .underlay-nav__container { box-sizing, max-width, margin-left, margin-right, padding-left, padding-right }',
    '.underlay-nav .underlay-nav__header { pointer-events }',
    '.underlay-nav .underlay-nav__logo, .underlay-nav .underlay-nav__toggle { pointer-events }',
    // Deep Research: the embedded workspace has its own Dashboard link
    '.underlay-nav-root--external .underlay-nav__header { visibility }',
    'body[data-menu-status="open"] .underlay-nav-root--external .underlay-nav__header, body[data-menu-status="closing"] .underlay-nav-root--external .underlay-nav__header { visibility }',
    '@media screen and (max-width: 767px) .underlay-nav .underlay-nav__logo { transition }',
    '@media screen and (max-width: 767px) body[data-menu-status="open"] .underlay-nav .underlay-nav__logo { opacity, pointer-events, transition }',
    'body[data-menu-status="open"] .app-toast-layer, body[data-menu-status="closing"] .app-toast-layer { opacity, visibility, pointer-events, transition }',
    '.underlay-nav .underlay-nav__menu { box-sizing, padding-top }',
    '.underlay-nav .underlay-nav__inner { padding-top }',
    '@media screen and (max-width: 767px) .underlay-nav .underlay-nav__menu { padding-top }',
    '@media screen and (min-width: 768px) .underlay-nav .underlay-nav__menu { font-size, padding-top }',
    '.underlay-nav .underlay-nav__toggle:focus { outline }',
    '.underlay-nav .underlay-nav__toggle:focus-visible { outline, outline-offset, border-radius }',
    // a11y: the logo (first Tab stop) shows a ring in its own ink on dark and light pages
    '.underlay-nav .underlay-nav__logo:focus-visible { outline, outline-offset, border-radius }',
    '.underlay-nav .underlay-nav__list { position }',
    '.underlay-nav .underlay-nav__hover-pill { position, left, width, top, height, background-color, border-radius, opacity, pointer-events, z-index, overflow, will-change }',
    '.underlay-nav .underlay-nav__pill-clone { position, top, left, width, display, flex-flow, color, pointer-events, user-select }',
    '.underlay-nav .underlay-nav__pill-link { width, padding }',
    '.underlay-nav .underlay-nav__pill-label { letter-spacing, font-family, font-size, line-height }',
    '@media screen and (max-width: 767px) .underlay-nav .underlay-nav__pill-label { font-size }',
    '.underlay-nav .underlay-nav__link-large { position, z-index, outline }',
    '.underlay-nav .underlay-nav__link-large:focus-visible { outline }',
    '.underlay-nav .underlay-nav__link-large.w--current { color, background-color }',
    '.underlay-nav .underlay-nav__header { --ul-u }',
    '@media screen and (max-width: 767px) .underlay-nav .underlay-nav__header { --ul-u }',
    '.underlay-nav .underlay-nav__logo { width, mix-blend-mode, display, align-items, gap }',
    // the spinning planet left of the word (owner 2026-11-22): 104 u, comes up once per page load
    '.underlay-nav .underlay-nav__logo-planet { display, flex, width, height, transition }',
    '.underlay-nav .underlay-nav__logo-planet.is--below { opacity, transform }',
    '.underlay-nav .underlay-nav__logo-planet-canvas { display, width, height }',
    '@media (prefers-reduced-motion: reduce) .underlay-nav .underlay-nav__logo-planet { transition }',
    '.underlay-nav .underlay-nav__logo-word { display, flex, width, height, overflow }',
    '.underlay-nav .underlay-nav__toggle-label { position, display, flex, align-items, justify-content, height }',
    '.underlay-nav .underlay-nav__toggle-word { display, flex, width, height, overflow }',
    '.underlay-nav .underlay-nav__toggle-sr { position, width, height, margin, padding, overflow, clip, white-space, border }',
    '.underlay-nav .underlay-nav__toggle-icon { font-size, width, gap, margin-bottom }',
    '.underlay-nav .underlay-nav__toggle-bar { height }',
    '.underlay-nav .underlay-nav__toggle { gap }',
    '@media screen and (max-width: 419px) .underlay-nav .underlay-nav__toggle { --ul-u }',
    '.underlay-nav .underlay-nav__bottom { flex-flow, gap, padding-left, padding-right }',
    '.underlay-nav .underlay-nav__bottom-col { row-gap, flex, width }',
    '.underlay-nav .underlay-nav__link-small.is--faded { opacity, color }',
    '.underlay-nav .underlay-nav__bottom .underlay-nav__link-small { font-size, font-weight }',
    // the rows and the bottom in the resource's own type, owner 2026-10-13
    '.underlay-nav .underlay-nav__bottom { font-family }',
    '@media screen and (max-width: 767px) .underlay-nav .underlay-nav__link-label, .underlay-nav .underlay-nav__pill-label { font-size }',
  ]);
  const header = parseCss(INDAGO).filter(r => /underlay-nav__header$/.test(r.selector) && r.decls[0][0] === 'color');
  assert.deepEqual(header.map(r => r.decls[0][1]), ['#0a0a0a', '#fff'], 'page ink on light pages, the resource #fff on dark ones');
  assert.doesNotMatch(CSS, /z-index: 70|mask-image|@keyframes|animation|mix-blend-mode: difference/);
  // the pill is the only row highlight: the resource's current-row box is cleared; the rows keep the resource type
  const current = parseCss(INDAGO).find(r => r.selector === '.underlay-nav .underlay-nav__link-large.w--current');
  assert.deepEqual(current.decls, [['color', 'inherit'], ['background-color', 'transparent']]);
  assert.ok(!parseCss(INDAGO).some(r => /underlay-nav__link-label/.test(r.selector) && r.decls.some(([k]) => k === 'font-family' || k === 'text-transform')), 'rows in the resource font, own case');
});

/* ── 3. JS ─────────────────────────────────────────────────────────────── */

function fakeElement(name, extra = {}) {
  const attrs = new Map();
  const listeners = {};
  return Object.assign({
    name, attrs, listeners, color: 'rgb(0, 0, 0)', hidden: false, isConnected: true, offsetWidth: 0,
    setAttribute(k, v) { attrs.set(k, String(v)); },
    getAttribute(k) { return attrs.has(k) ? attrs.get(k) : null; },
    hasAttribute(k) { return attrs.has(k); },
    removeAttribute(k) { attrs.delete(k); },
    addEventListener(type, fn) { (listeners[type] ||= new Set()).add(fn); },
    removeEventListener(type, fn) { listeners[type]?.delete(fn); },
    fire(type, init = {}) {
      const event = { type, target: this, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, ...init };
      for (const fn of [...(listeners[type] || [])]) fn(event);
      return event;
    },
    focus() { globalThis.document.activeElement = this; },
    blur() {},
    contains(node) { return node === this; },
    closest() { return null; },
    querySelectorAll() { return []; },
  }, extra);
}

function recordingGsap() {
  const sets = [];
  const timelines = [];
  const gsap = {
    registerPlugin(...plugins) { gsap.registered = plugins; },
    set(targets, vars) { sets.push([targets, vars]); },
    timeline(vars) {
      const tl = { vars, steps: [], ops: [], now: 0, total: 1.65, enterEnd: 1.05, active: false };
      for (const kind of ['set', 'to', 'fromTo', 'call']) tl[kind] = (...args) => (tl.steps.push([kind, ...args]), tl);
      tl.addPause = (...args) => (tl.steps.push(['addPause', ...args]), tl.paused = true, tl);
      // enterEndTime is read before addPause(): report the enter length until then
      tl.duration = () => (tl.paused ? tl.total : tl.enterEnd);
      tl.time = () => tl.now;
      tl.isActive = () => tl.active;
      for (const op of ['invalidate', 'play', 'reverse', 'restart', 'kill']) tl[op] = () => (tl.ops.push(op), tl);
      tl.timeScale = v => (tl.ops.push(`timeScale(${v})`), tl);
      tl.pause = t => (tl.ops.push(`pause(${t})`), t !== undefined && (tl.now = t), tl);
      timelines.push(tl);
      return tl;
    },
  };
  return { gsap, sets, timelines };
}

const rec = recordingGsap();
const customEase = { created: [], create(...args) { this.created.push(args); } };
globalThis.__gsapStub = rec.gsap;
globalThis.__customEaseStub = customEase;
globalThis.__prefetched = [];
const logic = await bundle({
  '@/lib/bodyScrollLock': 'export const acquireBodyScrollLock=()=>{globalThis.__locks=(globalThis.__locks||0)+1;return()=>{globalThis.__locks--;};};',
  '../lib/routePrefetch.js': 'export const prefetchRoute=()=>{};export const prefetchMenuRoutes=(r)=>{globalThis.__prefetched.push(r);};',
  'gsap': 'export default globalThis.__gsapStub;',
  'gsap/CustomEase': 'export const CustomEase=globalThis.__customEaseStub;',
}, 'export { initFixedUnderlayNavigation } from "./src/components/UnderlayNav.jsx";');

function fakeNav() {
  const named = (prefix, n) => Array.from({ length: n }, (_, i) => fakeElement(`${prefix}${i + 1}`));
  const nav = {
    toggle: fakeElement('toggle', { color: 'rgb(10, 10, 10)' }),
    labels: named('label', 2), bars: named('bar', 2),
    menu: fakeElement('menu', { color: 'rgb(49, 46, 46)', offsetWidth: 480 }),
    large: named('L', 8), small: named('S', 7),
    border: fakeElement('border'), main: fakeElement('main'), overlay: fakeElement('overlay'),
    dark: fakeElement('dark'), corners: named('corner', 2), rows: named('row', 2),
    header: fakeElement('header', { color: 'rgb(10, 10, 10)' }),
  };
  const bySelector = {
    '[data-underlay-nav-toggle]': nav.toggle, '.underlay-nav__toggle-label': nav.labels, '.underlay-nav__toggle-bar': nav.bars,
    '[data-underlay-nav-menu]': nav.menu, '[data-reveal-l]': nav.large, '[data-reveal-s]': nav.small,
    '.underlay-nav__bottom-border': nav.border, '[data-underlay-nav-overlay]': nav.overlay, '.underlay-nav__dark': nav.dark,
    '.underlay-nav__corner': nav.corners, '.underlay-nav__border-row': nav.rows, '.underlay-nav__header': nav.header,
  };
  nav.root = fakeElement('root', {
    querySelector: sel => bySelector[sel] ?? null,
    querySelectorAll: sel => bySelector[sel] ?? [],
    contains: node => Object.values(nav).flat().includes(node),
  });
  const body = fakeElement('body');
  globalThis.document = fakeElement('document', { body, activeElement: body, querySelector: sel => (sel === '[data-main]' ? nav.main : null) });
  globalThis.window = fakeElement('window');
  globalThis.HTMLElement = class {};
  globalThis.getComputedStyle = el => ({ color: el.color });
  globalThis.requestAnimationFrame = () => 0;
  globalThis.cancelAnimationFrame = () => {};
  return nav;
}

// targets as role names, function values as "fn", for comparison with the resource
function roles(nav) {
  const names = new Map();
  for (const [key, value] of Object.entries(nav)) {
    if (Array.isArray(value)) { names.set(value, key); value.forEach((el, i) => names.set(el, `${key}[${i}]`)); } else names.set(value, key);
  }
  const norm = v => (names.has(v) ? names.get(v) : Array.isArray(v) ? v.map(norm)
    : typeof v === 'function' ? 'fn' : v && typeof v === 'object' ? Object.fromEntries(Object.entries(v).map(([k, x]) => [k, norm(x)])) : v);
  return norm;
}

test('JS: CustomEase "energy" and the resource initial state', () => {
  assert.equal(rec.gsap.registered[0], customEase);
  assert.deepEqual(customEase.created, [['energy', 'M0,0 C0.32,0.72 0,1 1,1']]);
  const nav = fakeNav();
  rec.sets.length = 0;
  const cleanup = logic.initFixedUnderlayNavigation(nav.root, { mainSelector: '[data-main]' });
  const norm = roles(nav);
  assert.deepEqual(rec.sets.map(norm), [
    ['overlay', { visibility: 'hidden', pointerEvents: 'none' }],
    ['dark', { autoAlpha: 0 }],
    ['main', { x: 0 }],
    ['labels', { yPercent: 0 }],
    ['bars', { y: 0, rotation: 0 }],
    ['border', { scaleX: 0 }],
    ['rows[0]', { yPercent: -100 }],
    ['rows[1]', { yPercent: 100 }],
    ['corners', { scale: 0 }],
  ]);
  cleanup();
});

test('JS: one timeline, split by addPause, with the resource tweens, eases and easeReverse', () => {
  const nav = fakeNav();
  const cleanup = logic.initFixedUnderlayNavigation(nav.root, { mainSelector: '[data-main]' });
  const tl = rec.timelines.at(-1);
  const norm = roles(nav);
  assert.equal(tl.vars.paused, true);
  assert.deepEqual(tl.vars.defaults, { ease: 'energy', easeReverse: 'power2.inOut' });
  const steps = tl.steps.map(norm);
  assert.deepEqual(steps.slice(0, -1), [
    ['set', 'overlay', { visibility: 'visible', pointerEvents: 'auto' }, 0],
    ['to', ['main', 'overlay'], { x: 'fn', duration: 0.7 }, 0],
    ['to', 'dark', { autoAlpha: 1, duration: 0.5 }, 0],
    ['to', 'corners', { scale: 1, duration: 0.5 }, 0],
    ['to', 'rows', { yPercent: 0, duration: 0.5 }, 0],
    ['to', 'labels', { yPercent: -100, duration: 0.4 }, 0],
    ['to', 'toggle', { color: 'rgb(49, 46, 46)', duration: 0.4 }, 0],
    ['to', 'bars[0]', { y: '0.25em', rotation: 45, duration: 0.35, ease: 'back.out(1.4)', easeReverse: 'power3.out' }, 0.05],
    ['to', 'bars[1]', { y: '-0.25em', rotation: -45, duration: 0.35, ease: 'back.out(1.4)', easeReverse: 'power3.out' }, 0.05],
    ['fromTo', 'large', { autoAlpha: 0, xPercent: 25 }, { autoAlpha: 1, xPercent: 0, duration: 0.7, stagger: 0.05 }, 0],
    ['fromTo', 'small', { autoAlpha: 0, yPercent: 100 }, { autoAlpha: 1, yPercent: 0, duration: 0.5, stagger: 0.03, ease: 'power3.out' }, 0.3],
    ['to', 'border', { scaleX: 1, duration: 0.5 }, '<'],
    ['addPause'],
    ['to', ['large', 'small'], { autoAlpha: 0, duration: 0.3 }, '<'],
    ['to', ['main', 'overlay'], { x: 0, duration: 0.6 }, '<'],
    ['to', 'dark', { autoAlpha: 0, duration: 0.35, ease: 'power2.inOut' }, '<'],
    ['to', 'corners', { scale: 0, duration: 0.5 }, '<'],
    ['to', 'rows[0]', { yPercent: -100, duration: 0.5 }, '<'],
    ['to', 'rows[1]', { yPercent: 100, duration: 0.5 }, '<'],
    ['to', 'toggle', { color: 'fn', duration: 0.25 }, '<+=0.1'],
    ['to', 'labels', { yPercent: 0, duration: 0.25, ease: 'power3.in' }, '<'],
    ['to', 'bars', { y: 0, rotation: 0, duration: 0.25, ease: 'power3.in' }, '<'],
    ['set', 'overlay', { visibility: 'hidden', pointerEvents: 'none' }],
  ]);
  assert.deepEqual(steps.at(-1), ['call', 'fn'], 'Indago: the close landing call comes last');
  // x targets the menu width; the closing colour is the page colour under the header when the leg starts
  assert.equal(tl.steps[1][2].x(), -480);
  nav.header.color = 'rgb(255, 255, 255)';
  assert.equal(tl.steps[19][2].color(), 'rgb(255, 255, 255)');
  cleanup();
});

test('JS: the four-branch toggle, aria state and the body flag', () => {
  const nav = fakeNav();
  const cleanup = logic.initFixedUnderlayNavigation(nav.root, { mainSelector: '[data-main]' });
  const tl = rec.timelines.at(-1);
  const click = () => { tl.ops.length = 0; nav.toggle.fire('click'); return [...tl.ops]; };
  const status = () => document.body.getAttribute('data-menu-status');
  // 1. open from the start: invalidate + play
  assert.deepEqual(click(), ['invalidate', 'timeScale(1)', 'play']);
  assert.deepEqual([status(), nav.toggle.getAttribute('aria-expanded'), nav.toggle.getAttribute('aria-label')], ['open', 'true', 'close menu']);
  assert.equal(globalThis.__locks, 1);
  // 2. close while the open leg plays: reverse (with each tween's easeReverse)
  tl.now = 0.3;
  assert.deepEqual(click(), ['timeScale(1)', 'reverse']);
  assert.deepEqual([status(), nav.toggle.getAttribute('aria-expanded'), nav.toggle.getAttribute('aria-label')], ['closing', 'false', 'open menu']);
  assert.equal(globalThis.__locks, 0);
  // 3. open after a close (playhead past the pause): invalidate + restart
  tl.now = 1.65;
  assert.deepEqual(click(), ['invalidate', 'timeScale(1)', 'restart']);
  // 4. close from the pause: play into the exit half
  tl.now = 1.05;
  assert.deepEqual(click(), ['timeScale(1)', 'play']);
  // a close landing retires "closing" and hands the toggle colour back to the page CSS
  rec.sets.length = 0;
  tl.steps.at(-1)[1]();
  assert.equal(status(), '');
  assert.deepEqual(rec.sets.map(roles(nav)), [['toggle', { clearProps: 'color' }]]);
  status() === '' && document.body.setAttribute('data-menu-status', 'closing');
  tl.vars.onReverseComplete();
  assert.equal(status(), '');
  cleanup();
});

test('JS: overlay click, Escape, resize and router close behave as the resource', (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const nav = fakeNav();
  let close = null;
  const cleanup = logic.initFixedUnderlayNavigation(nav.root, { mainSelector: '[data-main]', exposeClose: (fn) => { close = fn; } });
  const tl = rec.timelines.at(-1);
  const status = () => document.body.getAttribute('data-menu-status');
  nav.overlay.fire('click');
  assert.equal(status(), null, 'overlay click while closed does nothing');
  document.fire('keydown', { key: 'Escape' });
  assert.equal(status(), null, 'Escape while closed does nothing');
  nav.toggle.fire('click');
  nav.overlay.fire('click');
  assert.equal(status(), 'closing', 'overlay click closes');
  nav.toggle.fire('click');
  document.activeElement = document.body;
  document.fire('keydown', { key: 'Escape' });
  assert.equal(status(), 'closing', 'Escape closes');
  assert.equal(document.activeElement, nav.toggle, 'and focuses the toggle');
  // resize: 150 ms debounce; open -> page and overlay to minus the menu width, closed -> invalidate
  nav.toggle.fire('click');
  rec.sets.length = 0;
  window.fire('resize');
  t.mock.timers.tick(149);
  assert.equal(rec.sets.length, 0);
  nav.menu.offsetWidth = 312;
  t.mock.timers.tick(1);
  assert.deepEqual(rec.sets.map(roles(nav)), [[['main', 'overlay'], { x: -312 }]]);
  close();
  assert.equal(status(), 'closing', 'router navigation closes through toggle()');
  tl.ops.length = 0;
  window.fire('resize');
  t.mock.timers.tick(150);
  assert.deepEqual(tl.ops, ['invalidate']);
  close();
  assert.equal(status(), 'closing', 'closing again is a no-op');
  cleanup();
});

test('JS: the workspace event opens only for an embedded host; cleanup removes what init added', () => {
  const nav = fakeNav();
  let external = false;
  const cleanup = logic.initFixedUnderlayNavigation(nav.root, { mainSelector: '[data-main]', isExternal: () => external });
  window.fire('indago:open-navigation', { detail: {} });
  assert.equal(document.body.getAttribute('data-menu-status'), null);
  external = true;
  window.fire('indago:open-navigation', { detail: {} });
  assert.equal(document.body.getAttribute('data-menu-status'), 'open');
  // StrictMode guard: a second binding on a bound root is refused
  assert.equal(logic.initFixedUnderlayNavigation(nav.root, { mainSelector: '[data-main]' }), undefined);
  const tl = rec.timelines.at(-1);
  cleanup();
  for (const el of [nav.toggle, nav.overlay, nav.menu, document, window]) {
    for (const [type, fns] of Object.entries(el.listeners)) assert.equal(fns.size, 0, `${el.name} ${type}`);
  }
  assert.ok(tl.ops.includes('kill'));
  assert.equal(document.body.getAttribute('data-menu-status'), '');
  assert.equal(globalThis.__locks, 0);
  assert.equal(nav.main.hasAttribute('inert'), false);
  assert.equal(nav.menu.hasAttribute('inert'), false);
  // after cleanup the root binds again
  const again = logic.initFixedUnderlayNavigation(nav.root, { mainSelector: '[data-main]' });
  assert.equal(typeof again, 'function');
  again();
});

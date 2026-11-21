// UI-SWEEP 2026-10-07 (beta readiness): every native button in the SPA must have an
// accessible name, and none may look clickable while doing nothing. Before this round
// five icon-only buttons (Query filter switch + dismiss, Report Viewer send + exit
// fullscreen, Screener AI "‹" back) had no name, and the Screener "🇯🇵 JP" market pill
// showed a pointer + hover with no handler (its only reason was a hover-only title).
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(here, '..', 'src');
const require = createRequire(import.meta.url);
const parser = require('@babel/parser');
const traverse = require('@babel/traverse').default;

function sources(dir) {
  const out = [];
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) out.push(...sources(p));
    else if (/\.jsx$/.test(e.name)) out.push(p);
  }
  return out;
}

const attr = (el, name) => el.attributes.find(a => a.type === 'JSXAttribute' && a.name && a.name.name === name);
const spread = el => el.attributes.some(a => a.type === 'JSXSpreadAttribute');
const tagName = el => (el.name.type === 'JSXIdentifier' ? el.name.name
  : el.name.type === 'JSXMemberExpression' && el.name.object.name === 'motion' ? el.name.property.name : '');

// Visible text of a node; a child expression or a labelled child counts as a name.
function named(node) {
  for (const c of node.children || []) {
    if (c.type === 'JSXText' && c.value.replace(/[\s‹›«»<>←→×✕+\-−…·]/g, '')) return true;
    if (c.type === 'JSXExpressionContainer' && c.expression.type !== 'JSXEmptyExpression') return true;
    if (c.type === 'JSXElement') {
      const el = c.openingElement;
      if (attr(el, 'aria-label') || attr(el, 'alt')) return true;
      if (/^(span|strong|em|b|i|div|p|small|kbd)$/.test(tagName(el)) && named(c)) return true;
    }
  }
  return false;
}

function buttons() {
  const found = [];
  for (const file of sources(SRC)) {
    const ast = parser.parse(readFileSync(file, 'utf8'), { sourceType: 'module', plugins: ['jsx'] });
    traverse(ast, {
      JSXElement(p) {
        const el = p.node.openingElement;
        if (tagName(el) !== 'button' || spread(el)) return;
        found.push({ where: `${path.relative(SRC, file)}:${el.loc.start.line}`, el, node: p.node });
      },
    });
  }
  return found;
}

test('every native button has an accessible name', () => {
  const unnamed = buttons()
    .filter(({ el, node }) => !attr(el, 'aria-label') && !attr(el, 'aria-labelledby') && !attr(el, 'title') && !named(node))
    .map(b => b.where);
  assert.deepEqual(unnamed, []);
});

test('a button with no handler is a submit, a DOM-wired hook, or marked aria-disabled', () => {
  const dead = buttons().filter(({ el }) => {
    if (el.attributes.some(a => a.type === 'JSXAttribute' && a.name && /^on(Click|PointerDown|MouseDown|PointerUp|TouchStart|KeyDown)$/.test(a.name.name))) return false;
    const type = attr(el, 'type');
    if (!type || (type.value && type.value.value === 'submit')) return false; // untyped buttons submit their form
    if (el.attributes.some(a => a.type === 'JSXAttribute' && a.name && /^data-/.test(a.name.name))) return false; // wired by a DOM listener
    const dis = attr(el, 'aria-disabled');
    if (dis && dis.value && dis.value.value === 'true') return false;
    return !attr(el, 'disabled');
  }).map(b => b.where);
  assert.deepEqual(dead, []);
});


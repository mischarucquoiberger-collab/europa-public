// The Dashboard menu's orange pill is the only focus indicator on its rows
// (.underlay-nav__link-large:focus-visible draws no outline), so it must follow
// keyboard focus. The pill effect is sliced from the real UnderlayNav.jsx (it
// holds no JSX) and run against a minimal fake menu: node has no DOM.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../src/components/UnderlayNav.jsx', import.meta.url), 'utf8');

function pillEffect() {
  const marker = source.indexOf('Magnetic hover pill');
  const start = source.indexOf('useEffect(() => {', marker);
  const end = source.indexOf('}, [currentPath]);', start);
  assert.ok(marker > 0 && start > marker && end > start, 'the pill effect is present');
  const body = source.slice(start + 'useEffect(() => {'.length, end);
  return new Function('listRef', 'pillRef', 'document', 'window', 'gsap', body);
}

/* A recording GSAP: to() lands at once (calling onUpdate) and is recorded
   with its duration; the ticker keeps its callbacks. */
function fakeGsap() {
  const tweens = [];
  const ticker = new Set();
  const killed = [];
  const apply = (target, vars) => {
    for (const [k, v] of Object.entries(vars)) {
      if (['duration', 'ease', 'overwrite', 'onUpdate'].includes(k)) continue;
      if (target.style && k === 'opacity') target.style.opacity = String(v); else target[k] = v;
    }
    vars.onUpdate?.();
  };
  return {
    tweens, ticker, killed,
    to(target, vars) { const t = { target, vars, kill() { killed.push(t); } }; tweens.push(t); apply(target, vars); return t; },
    set(target, vars) { apply(target, vars); },
    killTweensOf(target) { killed.push(target); },
    ticker: { add: fn => ticker.add(fn), remove: fn => ticker.delete(fn), fns: ticker },
  };
}

function fakeMenu({ media = {} } = {}) {
  const listeners = {};
  const list = {
    addEventListener: (type, fn) => { listeners[type] = fn; },
    removeEventListener: (type, fn) => { if (listeners[type] === fn) delete listeners[type]; },
    querySelector: sel => (sel === '.underlay-nav__link-large.w--current' ? links.find(l => l.current) : null),
    contains: el => el === list || links.includes(el),
    getBoundingClientRect: () => ({ top: 100 }),
  };
  const links = ['Home', 'Reports', 'Query', 'API'].map((label, i) => ({
    label, current: label === 'Query', visible: false, top: 100 + i * 50,
    closest(sel) { return sel === '.underlay-nav__link-large' ? this : null; },
    matches(sel) { assert.equal(sel, ':focus-visible'); return this.visible; },
    getBoundingClientRect() { return { top: this.top, height: 50 }; },
  }));
  const clone = { style: {}, children: [] };
  const pill = { style: {}, querySelector: sel => (sel === '.underlay-nav__pill-clone' ? clone : null) };
  list.children = [pill];
  const doc = { activeElement: null };
  const win = { addEventListener() {}, removeEventListener() {}, matchMedia: q => ({ matches: !!media[q] }) };
  const gsap = fakeGsap();
  const cleanup = pillEffect()({ current: list }, { current: pill }, doc, win, gsap);
  const row = label => links.find(l => l.label === label);
  const top = () => Number(/translate3d\(0, (-?[\d.]+)px, 0\)/.exec(pill.style.transform)?.[1]);
  const at = () => links.find(l => l.top - 100 === top() && pill.style.height === '50px')?.label;
  const focus = (label, visible) => {
    const link = row(label);
    link.visible = visible;
    doc.activeElement = link;
    listeners.focusin?.({ target: link });
  };
  return { listeners, row, at, top, focus, doc, cleanup, gsap, pill, clone };
}

test('the pill starts on the current page and follows a row reached by keyboard', () => {
  const menu = fakeMenu();
  assert.equal(menu.at(), 'Query');
  assert.equal(typeof menu.listeners.focusin, 'function', 'the menu list listens for focus');
  menu.focus('API', true);
  assert.equal(menu.at(), 'API');
  menu.focus('Home', true);
  assert.equal(menu.at(), 'Home');
});

test('the mouse leaving the list returns the pill to the keyboard-focused row, else the current page', () => {
  const menu = fakeMenu();
  menu.focus('API', true);
  menu.listeners.mouseover({ target: menu.row('Reports') });
  assert.equal(menu.at(), 'Reports');
  menu.listeners.mouseleave();
  assert.equal(menu.at(), 'API');
  // Focus leaves the rows (Tab past the list, or the menu closes): back to the current page.
  menu.doc.activeElement = null;
  menu.listeners.focusout({ relatedTarget: null });
  assert.equal(menu.at(), 'Query');
  menu.listeners.mouseover({ target: menu.row('Home') });
  menu.listeners.mouseleave();
  assert.equal(menu.at(), 'Query');
});

test('moving focus between rows does not bounce the pill to the current page', () => {
  const menu = fakeMenu();
  menu.focus('Home', true);
  menu.listeners.focusout({ relatedTarget: menu.row('Reports') });
  assert.equal(menu.at(), 'Home');
  menu.focus('Reports', true);
  assert.equal(menu.at(), 'Reports');
});

test('a mouse click focus (not :focus-visible) leaves the pill to the cursor rules', () => {
  const menu = fakeMenu();
  menu.focus('Reports', false);
  assert.equal(menu.at(), 'Query');
  menu.listeners.mouseleave();
  assert.equal(menu.at(), 'Query');
});

test('a browser without :focus-visible treats every focus as visible', () => {
  const menu = fakeMenu();
  menu.row('API').matches = () => { throw new SyntaxError("':focus-visible' is not a valid selector"); };
  menu.focus('API', false);
  assert.equal(menu.at(), 'API');
});

test('the effect cleanup removes the focus listeners with the mouse ones, the ticker and the tweens', () => {
  const menu = fakeMenu();
  assert.equal(menu.gsap.ticker.fns.size, 1, 'the light copy follows the row reveal per frame');
  menu.listeners.mouseover({ target: menu.row('API') });
  menu.cleanup();
  assert.deepEqual(Object.keys(menu.listeners), []);
  assert.equal(menu.gsap.ticker.fns.size, 0);
  assert.ok(menu.gsap.killed.includes(menu.pill), 'pill tweens killed');
});

test('liquid glide: the leading edge 0.3 s, the trailing edge 0.5 s, power3.out, landing on the row', () => {
  const menu = fakeMenu();
  const edgeTweens = () => menu.gsap.tweens.filter(t => t.target !== menu.pill).map(t => [Object.keys(t.vars)[0], t.vars.duration, t.vars.ease]);
  menu.listeners.mouseover({ target: menu.row('API') });          // down: bottom leads
  assert.deepEqual(edgeTweens(), [['top', 0.5, 'power3.out'], ['bottom', 0.3, 'power3.out']]);
  assert.equal(menu.at(), 'API');
  menu.gsap.tweens.length = 0;
  menu.listeners.mouseover({ target: menu.row('Home') });         // up: top leads
  assert.deepEqual(edgeTweens(), [['top', 0.3, 'power3.out'], ['bottom', 0.5, 'power3.out']]);
  assert.equal(menu.at(), 'Home');
});

test('the light label copy is shifted by -top so the pill is a window onto it', () => {
  const menu = fakeMenu();
  menu.listeners.mouseover({ target: menu.row('API') });
  assert.equal(menu.top(), 150);
  assert.equal(menu.clone.style.transform, 'translate3d(0, -150px, 0)');
});

test('reduced motion moves the pill instantly; devices without hover keep it on the current row', () => {
  const still = fakeMenu({ media: { '(prefers-reduced-motion: reduce)': true } });
  still.listeners.mouseover({ target: still.row('API') });
  assert.equal(still.at(), 'API');
  assert.equal(still.gsap.tweens.filter(t => t.target !== still.pill).length, 0, 'no edge tweens');
  const touch = fakeMenu({ media: { '(hover: none)': true } });
  touch.listeners.mouseover({ target: touch.row('API') });
  assert.equal(touch.at(), 'Query');
});

test('no hover decode: a hovered row keeps its name (owner 2026-10-13); the pill still glides', () => {
  assert.doesNotMatch(source, /decod|DECODE/i);
  assert.match(source, /const handleOver = \(e\) => \{[\s\S]*?positionPillOver\(link\);\s*\};/);
});

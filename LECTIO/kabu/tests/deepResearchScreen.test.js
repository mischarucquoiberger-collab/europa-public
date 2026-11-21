// The Deep Research screen in this build: the CALLISTO lettering, the Callisto name in what people
// see and hear, and the 'offline' phase (no workspace service): the splash plays out and leaves a
// quiet notice instead of retrying into "Unable to open Deep Research".
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  GROUND, LOCKUP_TEXT, WIPE_LOGO_PATHS, WIPE_LOGO_TEXT, WIPE_LOGO_VIEWBOX, WORDMARK_OUTLINE, WORDMARK_PATHS, WORDMARK_VIEW,
  capHeightFor, lockupLayout, percentTarget,
} from '../src/lib/drSplashLusion.js';
import { classifyStatus, loaderView, BUSY_STARTING_MESSAGE } from '../src/pages/dr2Loader.js';

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');

test('the lockup draws only CALLISTO, in the header lettering: eight frozen paths', () => {
  assert.equal(WORDMARK_PATHS.length, 8);
  // the letters' visible box, the 3-unit outline included
  assert.deepEqual({ ...WORDMARK_VIEW }, { x: -1.5, y: 65.5, w: 706.75, h: 49 });
  assert.equal(WORDMARK_OUTLINE, 3);
  assert.equal(WORDMARK_PATHS.map((p) => p.ch).join(''), 'CALLISTO');
  // no words beside it on the first screen; the swipe after it says just DEEP RESEARCH
  assert.equal(LOCKUP_TEXT, '');
  assert.equal(WIPE_LOGO_TEXT, 'DEEP RESEARCH');
  assert.equal(WIPE_LOGO_PATHS.map((p) => p.ch).join(''), 'DEEPRESEARCH');
  assert.equal(WIPE_LOGO_VIEWBOX, '0 -32 27475 1600');
  // big: the wipe logo's height on a desktop, never wider than 84% of the screen
  assert.equal(capHeightFor(48), 51);
  assert.equal(capHeightFor(4), 14);
  const wide = lockupLayout(48, () => 0);
  assert.equal(wide.letters.length, 0);
  assert.equal(wide.gap, 0);
  assert.ok(Math.abs(wide.width - wide.markWidth) < 1e-9);
  assert.ok(lockupLayout(48, () => 0, 300).width <= 300 + 1e-9);
  assert.ok(Object.isFrozen(WORDMARK_PATHS) && Object.isFrozen(WORDMARK_VIEW));
  for (const path of WORDMARK_PATHS) {
    assert.ok(Object.isFrozen(path));
    assert.equal(typeof path.d, 'string');
  }
  // C, S and O are centre-line strokes; the rest are filled
  assert.deepEqual(WORDMARK_PATHS.map((p) => p.stroke || 0), [10.5, 0, 0, 0, 0, 10.5, 0, 10.5]);
  assert.equal(WORDMARK_PATHS[0].d, 'M57.75 71H12.75q-9 0-9 9v20q0 9 9 9h45');
  assert.equal(WORDMARK_PATHS[7].d, 'M657 71h33q10 0 10 9v20q0 9-10 9h-33q-10 0-10-9V80q0-9 10-9Z');
});

test('the splash ground is the brand navy, not black', () => {
  assert.equal(GROUND, '#0e1420');
  const css = read('src/pages/DrSplash.css') + read('src/pages/DeepResearch2.css');
  assert.doesNotMatch(css, /background(-color)?:\s*(#000\b|#000000|black\b)/);
  assert.doesNotMatch(read('src/lib/drSplashLusion.js'), /'#000'/);
});

test('no user-visible "Indago" in the splash or the loader messages', () => {
  const splash = read('src/pages/DrSplash.jsx');
  assert.match(splash, /<h1 className="dr2-splash__sr">Callisto<\/h1>/);
  // JSX text and string literals (the imported navigation helper's identifier is not text)
  const visible = splash.match(/>[^<>{}]*</g).join(' ') + (splash.match(/'[^'\n]*'/g) || []).join(' ');
  assert.doesNotMatch(visible.replace(/data-indago-surface/g, ''), /Indago/);
  const loader = read('src/pages/dr2Loader.js');
  const messages = (loader.match(/'[^'\n]*'/g) || []).filter((s) => / /.test(s));
  for (const message of messages) assert.doesNotMatch(message, /Indago/, message);
  assert.match(BUSY_STARTING_MESSAGE, /^The server is busy, so Callisto is starting slowly/);
  const slow = loaderView({ phase: 'opening', elapsed: 60_000, estimate: 8_000, signals: null, expected: 0 });
  assert.match(slow.eta, /The Callisto server may be busy/);
});

test('status: no workspace service is the terminal offline phase; a busy service still retries', () => {
  assert.equal(classifyStatus({ status: 404 }), 'offline');
  assert.equal(classifyStatus({ status: 200, json: false }), 'offline');
  assert.equal(classifyStatus({ status: 0, failed: true }), 'offline');
  assert.equal(classifyStatus({ status: 0, aborted: true }), 'retry');       // our own timeout
  assert.equal(classifyStatus({ status: 200, ready: false }), 'retry');      // starting
  for (const status of [502, 503, 504]) assert.equal(classifyStatus({ status }), 'retry');
  assert.equal(classifyStatus({ status: 200, ready: true }), 'ok');
  assert.equal(classifyStatus({ status: 401 }), 'session');
  // the splash runs to 100 and leaves on offline, as on ready
  assert.equal(percentTarget('offline', 12), 1);
  assert.match(read('src/pages/DrSplash.jsx'), /const ready = phase === 'ready' \|\| phase === 'offline';/);
});

test('the page shows the offline surface (no frame) and reports the splash gone', () => {
  const page = read('src/pages/DeepResearch.jsx');
  assert.match(page, /if \(verdict === 'offline'\) \{ setPhase\('offline'\); return; \}/);
  assert.match(page, /data-testid="dr2-offline"/);
  assert.match(page, /<h2 className="dr2-offline__sr">Callisto<\/h2>/);
  assert.match(page, /The research workspace is not connected in this build yet\./);
  // the frame mounts only while checking / opening / ready
  assert.match(page, /\{phase === 'checking' \|\| phase === 'opening' \|\| ready \? \(\s*<iframe/);
  // the splash state reported upward goes false once the splash is done (offline is not 'error')
  assert.match(page, /const splashUp = !splashDone \|\| phase === 'error';/);
  // the wipe uncovers the offline surface
  assert.match(read('src/pages/DrSplash.jsx'), /\[data-testid="dr2-offline"\]/);
  assert.match(read('src/pages/DeepResearch2.css'), /\.dr2-offline \{[\s\S]*?background: #0e1420;/);
});

// The splash: the logo reveal loader, inside the app. It plays over the app on every page load
// and lifts straight onto the page beneath: no start button before it, no page between it and
// the app (owner 2026-11-22). The company name is the header's lettering.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');
const splash = read('src/components/EuropaSplash.jsx');
const app = read('src/App.jsx');
const page = read('index.html');

// index.html's pre-paint script, run on a hash: true when this load paints the splash ground.
// Storage throws on any touch, so a script that reads or writes a flag fails here.
const prePaint = page.match(/<script>([\s\S]*?)<\/script>/)[1];
const forbidden = new Proxy({}, { get() { throw new Error('the splash rule must not use storage'); } });
function splashOnLoad(hash) {
  let enabled;
  const doc = { documentElement: { classList: { toggle: (name, value) => { assert.equal(name, 'splash'); enabled = value; } } } };
  new Function('location', 'document', 'localStorage', 'sessionStorage', prePaint)({ hash }, doc, forbidden, forbidden);
  return enabled;
}

test('the splash plays on every full load and reload: no storage flag, any page of the app', () => {
  for (const hash of ['', '#/', '#/Home', '#/home', '#/Reports', '#/DeepResearch', '#/Viewer?id=1', '#/Home?ticker=NVDA']) {
    assert.equal(splashOnLoad(hash), true, hash);
    assert.equal(splashOnLoad(hash), true, `${hash} (reload)`);
  }
  assert.doesNotMatch(page, /localStorage|sessionStorage|europa-intro-seen/);
  assert.doesNotMatch(splash, /localStorage|sessionStorage|europa-intro-seen/);
});

test('a page= deep link into the markets desk (a chart or brief in a new tab) opens without the splash', () => {
  for (const hash of ['#/Home?page=%2Fstocks%2FNVDA', '#/Home?page=/stocks/NVDA', '#/Home?page=%2Fstocks%2FBRK.B',
    '#/Home?page=%2Fstocks%2FI%3ASPX', '#/Home?page=%2Freports', '#/Home?page=%2Freports%3Fticker%3DAAPL', '#/home?page=/stocks/msft']) {
    assert.equal(splashOnLoad(hash), false, hash);
  }
  // Not a desk page (LectioHome ignores these), or not Home: the splash plays as on any load.
  for (const hash of ['#/Home?page=%2F%2Fevil.example', '#/Home?page=%2Fstocks%2F..%2F..%2Fx', '#/Home?page=%2Fstocks%2F..',
    '#/Home?page=https%3A%2F%2Fevil.example%2Fstocks%2FX', '#/Home?page=', '#/Reports?page=%2Fstocks%2FNVDA', '#/Home?page=%2Freportsx']) {
    assert.equal(splashOnLoad(hash), true, hash);
  }
});

test('the component follows the class index.html set before the first paint, once per load', () => {
  assert.match(splash, /function splashDue\(\) \{\s*return !played && document\.documentElement\.classList\.contains\("splash"\);\s*\}/);
  assert.match(splash, /useState\(\(\) => !splashDue\(\)\)/);
  assert.match(splash, /if \(!splashDue\(\)\) \{ releaseGround\(\); return undefined; \}\s*played = true;/);
});

test('there is no separate splash page and no moon page behind it', () => {
  assert.equal(existsSync(new URL('../public/splash', import.meta.url)), false);
  assert.equal(existsSync(new URL('../dev/copy_splash.py', import.meta.url)), false);
  assert.doesNotMatch(app, /SPLASH_URL|SplashEntry|location\.replace/);
  assert.match(app, /<Route path="\/" element=\{<Navigate to=\{HOME_ROUTE\} replace \/>\} \/>/);
});

test('the timeline is the loader as supplied: 3 s reveal, fade, the curtain lifts, then it is gone', () => {
  assert.match(splash, /export const SPLASH_EASE = "0\.65, 0\.01, 0\.05, 0\.99";/);
  assert.match(splash, /CustomEase\.create\("loader", SPLASH_EASE\);/);
  assert.match(splash, /defaults: \{\s*ease: "loader",\s*duration: 3,\s*\},\s*onComplete: \(\) => setGone\(true\),/);
  const steps = [
    '.set(wrap, { display: "block" })',
    '.to(progressBar, { scaleX: 1 })',
    '.to(logo, { clipPath: "inset(0% 0% 0% 0%)" }, "<")',
    '.to(container, { autoAlpha: 0, duration: 0.5 })',
    '.to(progressBar, { scaleX: 0, transformOrigin: "right center", duration: 0.5 }, "<")',
    '.add("hideContent", "<")',
    '.to(bg, { yPercent: -101, duration: 1 }, "hideContent")',
    '.set(wrap, { display: "none" });',
  ];
  let at = 0;
  for (const step of steps) {
    const next = splash.indexOf(step, at);
    assert.ok(next > at, step);
    at = next;
  }
  assert.match(splash, /new SplitText\(textElements\[0\], \{ type: "lines,chars", mask: "lines" \}\)/);
  assert.match(splash, /return \(\) => \{\s*loadTimeline\.kill\(\);\s*firstWord\.revert\(\);\s*secondWord\.revert\(\);\s*releaseGround\(\);\s*\};/);
});

test('the two lines and the company name in the header lettering, in both layers of the reveal', () => {
  assert.match(splash, /export const SPLASH_LINES = Object\.freeze\(\["Searching for life", "Finding financial life"\]\);/);
  assert.match(splash, /const WORD = letteringWord\("Europa"\);/);
  assert.match(splash, /<div className="loader__logo-item is--base">\s*<Wordmark \/>\s*<\/div>\s*<div data-load-logo className="loader__logo-item is--top">\s*<Wordmark \/>/);
  assert.match(splash, /fill="currentColor"\s*stroke="currentColor"\s*strokeWidth="3"\s*strokeLinejoin="round"/);
  assert.doesNotMatch(splash, /<text|Helvetica/);
  assert.match(splash, /\.europa-splash \.loader__logo-item\.is--top \{\s*-webkit-clip-path: inset\(0% 100% 0% 0%\);\s*clip-path: inset\(0% 100% 0% 0%\);/);
  assert.match(splash, /\.europa-splash \.loader__bg \{\s*background-color: #0a0a0a;/);
  assert.match(splash, /\.europa-splash\.loader \{\s*z-index: 10050;/);
});

test('first paint is the splash ground, and the app ground returns when the curtain lifts', () => {
  assert.match(page, /<html lang="en" class="splash">/);
  assert.match(page, /html\.splash,html\.splash body\{background:#0a0a0a !important\}/);
  assert.match(splash, /document\.documentElement\.classList\.remove\("splash"\);/);
  assert.match(splash, /loadTimeline\.call\(releaseGround, null, "hideContent"\);/);
  // reduced motion: no animation, the app shows at once
  assert.match(splash, /window\.matchMedia\?\.\("\(prefers-reduced-motion: reduce\)"\)\.matches\) \{\s*releaseGround\(\);\s*setGone\(true\);/);
});

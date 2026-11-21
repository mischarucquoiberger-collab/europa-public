// The logo's planet (owner 2026-11-22): Europa, spinning, in coloured ASCII,
// left of the word EUROPA. The renderer's pure helpers (ported from the live
// ASCII moon), its grid sizing, and the component's contract: decorative,
// the entrance once per page load, reduced motion honoured, the GL context
// released on unmount.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { build } from 'esbuild';
import {
  rotX, rotY, rotZ, mul, apply, applyT, norm, hash, viewMatrix, prepareTexture, gridFor,
  lutIndex, buildLUTFromVectors, arrivalDelay, NG, Q, EUROPA, CELL_CSS, DISC,
} from '../src/components/asciiMoon.js';

const require = createRequire(import.meta.url);
const root = fileURLToPath(new URL('../', import.meta.url));
const read = path => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');
const close = (a, b, msg) => a.forEach((v, i) => assert.ok(Math.abs(v - b[i]) < 1e-9, `${msg}: ${a} vs ${b}`));

test('matrix helpers: row-major 3x3 rotations, product, transpose-apply, normalise', () => {
  close(rotX(0), [1, 0, 0, 0, 1, 0, 0, 0, 1], 'rotX(0) is the identity');
  close(apply(rotZ(Math.PI / 2), [1, 0, 0]), [0, 1, 0], 'rotZ turns x into y');
  close(apply(rotX(Math.PI / 2), [0, 1, 0]), [0, 0, 1], 'rotX turns y into z');
  close(apply(rotY(Math.PI / 2), [0, 0, 1]), [1, 0, 0], 'rotY turns z into x');
  const M = mul(rotZ(0.3), mul(rotX(-0.7), rotY(1.1)));
  close(mul(M, rotX(0)), M, 'identity on the right');
  close(applyT(M, apply(M, [0.2, -0.5, 0.8])), [0.2, -0.5, 0.8], 'a rotation\'s transpose undoes it');
  close(apply(mul(rotZ(0.4), rotX(0.9)), [1, 2, 3]), apply(rotZ(0.4), apply(rotX(0.9), [1, 2, 3])), 'mul composes');
  assert.ok(Math.abs(Math.hypot(...norm([3, -4, 12])) - 1) < 1e-12);
  // Europa's view: M = rotZ(roll) * rotX(tilt), roll 0.10, tilt 0.20; the sun from the upper left, in front
  assert.deepEqual([EUROPA.roll, EUROPA.tilt, EUROPA.theta, EUROPA.relief], [0.10, 0.20, 3.6, 3.2]);
  assert.deepEqual([...EUROPA.sun], [-0.62, 0.36, 0.70]);
  close(viewMatrix(), mul(rotZ(0.10), rotX(0.20)), 'view matrix');
});

test('hash: the source\'s integer hash, deterministic, uniform in [0, 1)', () => {
  // reference values from TEST/moon.js's hash()
  const ref = n => { n = Math.imul(n ^ (n >>> 15), 0x2c1b3c6d); n = Math.imul(n ^ (n >>> 12), 0x297a2d39); return ((n ^ (n >>> 15)) >>> 0) / 4294967296; };
  for (const n of [0, 1, 9, 13, 977, 7919 * 5 + 13, 2 ** 31 - 1]) assert.equal(hash(n), ref(n));
  let sum = 0;
  for (let i = 0; i < 20000; i++) { const h = hash(i * 101 + 9); assert.ok(h >= 0 && h < 1); sum += h; }
  assert.ok(Math.abs(sum / 20000 - 0.5) < 0.01, 'about uniform');
});

test('texture: brightness is albedo, the rest is hue; gradients wrap in longitude and clamp at the poles', () => {
  // 3 x 2 RGBA map: ice-blue, rust, black / grey, white, dark blue
  const px = [[150, 200, 255], [200, 100, 50], [0, 0, 0], [128, 128, 128], [255, 255, 255], [0, 0, 51]];
  const data = new Uint8ClampedArray(px.flatMap(([r, g, b]) => [r, g, b, 255]));
  const T = prepareTexture({ width: 3, height: 2, data });
  assert.equal(T.W, 3); assert.equal(T.H, 2);
  const mx = px.map(p => Math.max(p[0] / 255, p[1] / 255, p[2] / 255, 1e-3));
  mx.forEach((m, i) => assert.ok(Math.abs(T.alb[i] - Math.min(1, m * 1.02 + 0.02)) < 1e-6, `albedo ${i}`));
  // hue: the colour divided by its brightest channel (ice-blue keeps blue at 1, rust keeps red at 1)
  close([...T.rgb.slice(0, 3)].map(v => +v.toFixed(5)), [150 / 255, 200 / 255, 1].map(v => +(v / 1).toFixed(5)), 'ice-blue hue');
  close([...T.rgb.slice(3, 6)].map(v => +v.toFixed(5)), [1, 0.5, 0.25], 'rust hue');
  // gu: east minus west neighbour (wrapping), stretched by 1 / max(0.3, cos(latitude))
  const stretch = 1 / Math.max(0.3, Math.cos((0.5 - 0.5 / 2) * Math.PI));
  assert.ok(Math.abs(T.gu[0] - (T.alb[1] - T.alb[2]) * stretch) < 1e-6, 'gu wraps west of x=0 to x=W-1');
  assert.ok(Math.abs(T.gu[2] - (T.alb[0] - T.alb[1]) * stretch) < 1e-6, 'gu wraps east of x=W-1 to x=0');
  // gv: the row above minus the row below, clamped at the edges
  assert.ok(Math.abs(T.gv[0] - (T.alb[0] - T.alb[3])) < 1e-6);
  assert.ok(Math.abs(T.gv[4] - (T.alb[1] - T.alb[4])) < 1e-6);
});

test('grid: square, cells 1:2, sized from the canvas\'s CSS size, rendered at twice the device resolution', () => {
  assert.equal(CELL_CSS, 1.25);
  assert.equal(DISC, 0.48, 'the disc fills 96% of the canvas');
  // desktop: 104 u x 0.29959 px = 31.16 px at dpr 2 -> 24 x 12 cells of 5 x 10 internal px
  assert.deepEqual(gridFor(104 * 0.29959, 2), { cols: 24, rows: 12, cw: 5, ch: 10, width: 120, height: 120 });
  for (const [css, dpr] of [[31.16, 1], [31.16, 3], [19.1, 3], [15.1, 2], [8, 1], [200, 2]]) {
    const g = gridFor(css, dpr);
    assert.equal(g.cols, g.rows * 2, 'twice as many columns as rows');
    assert.equal(g.ch, g.cw * 2, 'cells 1:2');
    assert.equal(g.width, g.height, 'square');
    assert.ok(g.rows >= 4 && g.cw >= 4);
    const cellCss = css / g.cols;
    if (css > 20) assert.ok(cellCss > 1 && cellCss < 2, `cell ${cellCss} CSS px`);
    if (g.cw > 4) assert.ok(Math.abs(g.cw - cellCss * dpr * 2) <= 0.5, 'twice the device resolution');
  }
});

test('shape matching: the lookup table maps a 2x3 block to the best-fitting glyph', () => {
  assert.equal(NG, 95); assert.equal(Q, 6);
  assert.equal(lutIndex(1, 0, 0, 0, 0, 0), 1);
  assert.equal(lutIndex(0, 0, 0, 0, 0, 1), Q ** 5);
  assert.equal(lutIndex(5, 5, 5, 5, 5, 5), Q ** 6 - 1);
  // synthetic glyphs: 0 blank, 1 full, 2 left column, 3 top row, the rest grey
  const vec = new Float32Array(NG * 6).fill(0.5);
  vec.set([0, 0, 0, 0, 0, 0], 0); vec.set([1, 1, 1, 1, 1, 1], 6); vec.set([1, 0, 1, 0, 1, 0], 12); vec.set([1, 1, 0, 0, 0, 0], 18);
  const LUT = buildLUTFromVectors(vec);
  assert.equal(LUT.length, Q ** 6);
  assert.equal(LUT[0], 0, 'no ink: blank');
  assert.equal(LUT[lutIndex(5, 5, 5, 5, 5, 5)], 1);
  assert.equal(LUT[lutIndex(5, 0, 5, 0, 5, 0)], 2);
  assert.equal(LUT[lutIndex(5, 5, 0, 0, 0, 0)], 3);
  assert.equal(LUT[lutIndex(3, 2, 3, 2, 2, 3)], 4, 'mid tones: the first grey glyph');
});

test('arrival: cells resolve outward from the centre', () => {
  const cols = 24, rows = 12, cw = 5, ch = 10, radius = 120 * DISC;
  const centre = arrivalDelay(rows / 2 * cols + cols / 2, cols, rows, cw, ch, radius);
  const corner = arrivalDelay(0, cols, rows, cw, ch, radius);
  assert.ok(centre >= 0.1 && centre <= 0.5, `centre ${centre}`);
  assert.ok(corner >= 0.1 + 1.05 * 1.0 && corner <= 0.1 + 1.05 * 1.3 + 0.4, `corner ${corner}`);
});

test('renderer: transparent ground, the source\'s light and spin, the context released on destroy', () => {
  const src = read('src/components/asciiMoon.js');
  assert.match(src, /getContext\("webgl", \{ alpha: true, premultipliedAlpha: true, antialias: false/);
  assert.match(src, /gl_FragColor = vec4\(col, max\(col\.r, max\(col\.g, col\.b\)\)\)/, 'premultiplied, alpha 0 without ink');
  assert.match(src, /period: 24,/, 'one rotation about every 24 s');
  assert.match(src, /if \(!gl \|\| gl\.isContextLost\(\)\) return null;/, 'null without WebGL');
  const destroy = src.slice(src.indexOf('destroy() {'));
  assert.match(destroy, /stop\(\);/);
  assert.match(destroy, /deleteTexture[\s\S]*deleteBuffer[\s\S]*deleteProgram[\s\S]*lose\(\);/);
  assert.match(src, /const lose = \(\) => gl\?\.getExtension\("WEBGL_lose_context"\)\?\.loseContext\(\);/);
  assert.match(src, /cancelAnimationFrame\(raf\)/);
  // one lookup table for every instance, built off the render path
  assert.match(src, /let sharedLUT = null;/);
  assert.match(src, /requestIdleCallback\(run/);
  // no globals, no input handlers in the logo
  assert.doesNotMatch(src, /window\.MOON|addEventListener|getElementById/);
});

async function logoPlanetHarness() {
  const output = await build({
    stdin: { contents: 'export { default } from "./src/components/LogoPlanet.jsx";', resolveDir: root, loader: 'jsx' },
    bundle: true, write: false, platform: 'node', format: 'cjs', jsx: 'automatic',
    external: ['react', 'react/*', 'react-dom', 'react-dom/*'], logLevel: 'silent',
  });
  const module = { exports: {} };
  new Function('require', 'module', 'exports', output.outputFiles[0].text)(require, module, module.exports);
  return module.exports.default;
}

test('component: a decorative span around one canvas, waiting below before its entrance', async () => {
  const LogoPlanet = await logoPlanetHarness();
  const html = renderToStaticMarkup(React.createElement(LogoPlanet));
  assert.equal(html, '<span class="underlay-nav__logo-planet is--below" aria-hidden="true"><canvas class="underlay-nav__logo-planet-canvas"></canvas></span>');
  assert.equal(renderToStaticMarkup(React.createElement(LogoPlanet)), html, 'rendering never consumes the entrance');
});

test('component: entrance once per page load, reduced motion honoured, cleaned up on unmount', () => {
  const src = read('src/components/LogoPlanet.jsx');
  // a module-level flag, read at mount and set once a renderer has started
  assert.match(src, /^let entrancePlayed = false;$/m);
  assert.match(src, /const \[rising\] = useState\(\(\) => !entrancePlayed\);/);
  assert.match(src, /moon\.start\(\);/);
  assert.equal((src.match(/entrancePlayed = true;/g) || []).length, 1);
  assert.ok(src.indexOf('entrancePlayed = true;') > src.indexOf('if (!moon) { setFailed(true); return; }'), 'set only when the renderer runs');
  assert.match(src, /className=\{`underlay-nav__logo-planet\$\{rising && !up \? " is--below" : ""\}`\}/, 'only the rising mount waits below');
  assert.match(src, /arrival: rising && !still/, 'the glyph arrival plays with the entrance only');
  // reduced motion: one still frame, no arrival
  assert.match(src, /matchMedia\?\.\("\(prefers-reduced-motion: reduce\)"\)/);
  assert.match(src, /createAsciiMoon\(canvas, \{ texture, arrival: rising && !still, still \}\)/);
  const css = read('src/components/UnderlayNav.jsx');
  assert.match(css, /@media \(prefers-reduced-motion: reduce\) \{\n {2}\.underlay-nav \.underlay-nav__logo-planet \{\n {4}transition: none;/);
  // the entrance is transform and opacity only, about 0.9 s, ease-out, about 10 px up
  assert.match(css, /transition: opacity 0\.9s cubic-bezier\(0\.22, 1, 0\.36, 1\), transform 0\.9s cubic-bezier\(0\.22, 1, 0\.36, 1\);/);
  assert.match(css, /\.is--below \{\n {2}opacity: 0;\n {2}transform: translateY\(10px\) scale\(0\.6\);\n\}/);
  // unmount: the renderer is destroyed (its GL context released), observers dropped
  const cleanup = src.slice(src.indexOf('return () => {'));
  assert.match(cleanup, /cancelled = true;[\s\S]*sizeObserver\?\.disconnect\(\);[\s\S]*removeEventListener\("change", onDpr\);[\s\S]*moon\?\.destroy\(\);/);
  // without WebGL or the texture: nothing rendered, no space reserved
  assert.match(src, /if \(failed\) return null;/);
  // the texture by URL (no image import, so the esbuild render tests bundle it)
  assert.match(src, /export const PLANET_TEXTURE_URL = "\/europa-tex\.png";/);
  assert.doesNotMatch(src, /import [^;]*\.png/);
  assert.match(css, /<LogoPlanet \/>\n\s*<LetteringLabel word="Europa" className="underlay-nav__logo-word" \/>/, 'inside the logo, before the word');
});

test('texture asset: public/europa-tex.png is a 256 x 128 PNG', () => {
  const png = readFileSync(new URL('../public/europa-tex.png', import.meta.url));
  assert.equal(png.subarray(1, 4).toString('latin1'), 'PNG');
  assert.deepEqual([png.readUInt32BE(16), png.readUInt32BE(20)], [256, 128]);
});

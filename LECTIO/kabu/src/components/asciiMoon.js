/* Live ASCII moon, the logo's planet: a port of the "live ASCII moon"
 * renderer (TEST/moon.js) as a module with no globals, set up for Europa.
 *
 * The algorithm is the source's: shape-matched glyphs (each character cell
 * is sampled as 2x3 sub-cells and a lookup table picks the printable ASCII
 * glyph whose ink fits those six samples best), relief lighting from the
 * albedo gradients of a true-colour map, the colour of each cell taken from
 * the map's hue, and the arrival (cells resolve outward from the centre out
 * of scrambled glyphs, with a brief white flash).
 *
 * What a logo needs on top: a transparent ground (premultiplied colour with
 * alpha 0 where there is no planet ink), a grid taken from the canvas's CSS
 * size (square, the disc fills 96% of it), rendering at about twice the
 * device resolution so the glyphs are antialiased by downsampling, a faster
 * spin, and a destroy() that releases the GL context. Pointer, wheel and
 * keyboard controls, the other palettes, stars, labels, the probe, the
 * departure scatter, the toast and the non-rgb (Callisto) hue ramp are left
 * out. */

export const NG = 95;                              // printable ASCII 32..126
export const Q = 6;                                // quantisation levels per sub-cell sample
const TAU = Math.PI * 2;

/** Europa as set in TEST/europa.html, with a spin a logo can show. */
export const EUROPA = Object.freeze({
  relief: 3.2,
  period: 24,              // seconds per rotation (the source's 150 s is invisible at logo size)
  theta: 3.6,
  roll: 0.10,
  tilt: 0.20,
  sun: Object.freeze([-0.62, 0.36, 0.70]),
});

/** Character cell width in CSS px, and how many internal pixels render each device pixel. */
export const CELL_CSS = 1.25;
export const SUPERSAMPLE = 2;
/** Ink gain: at logo size each glyph is averaged with its gaps by the
 *  downsampling, so its strokes are lifted to read as bright as the source's. */
export const INK = 1.3;
/** The disc's radius as a fraction of the (square) canvas side: it fills 96%. */
export const DISC = 0.48;

/* ── tiny matrix helpers (row-major 3x3) ─────────────────────────────── */
export function rotX(a) { const c = Math.cos(a), s = Math.sin(a); return [1, 0, 0, 0, c, -s, 0, s, c]; }
export function rotY(a) { const c = Math.cos(a), s = Math.sin(a); return [c, 0, s, 0, 1, 0, -s, 0, c]; }
export function rotZ(a) { const c = Math.cos(a), s = Math.sin(a); return [c, -s, 0, s, c, 0, 0, 0, 1]; }
export function mul(a, b) {
  const o = new Array(9);
  for (let r = 0; r < 3; r++) for (let c = 0; c < 3; c++)
    o[r * 3 + c] = a[r * 3] * b[c] + a[r * 3 + 1] * b[3 + c] + a[r * 3 + 2] * b[6 + c];
  return o;
}
export function apply(m, v) { return [m[0] * v[0] + m[1] * v[1] + m[2] * v[2], m[3] * v[0] + m[4] * v[1] + m[5] * v[2], m[6] * v[0] + m[7] * v[1] + m[8] * v[2]]; }
export function applyT(m, v) { return [m[0] * v[0] + m[3] * v[1] + m[6] * v[2], m[1] * v[0] + m[4] * v[1] + m[7] * v[2], m[2] * v[0] + m[5] * v[1] + m[8] * v[2]]; }
export function norm(v) { const l = Math.hypot(v[0], v[1], v[2]); return [v[0] / l, v[1] / l, v[2] / l]; }
export function hash(n) { n = Math.imul(n ^ (n >>> 15), 0x2c1b3c6d); n = Math.imul(n ^ (n >>> 12), 0x297a2d39); return ((n ^ (n >>> 15)) >>> 0) / 4294967296; }

/** The view: M = rotZ(roll) * rotX(tilt). */
export function viewMatrix(roll = EUROPA.roll, tilt = EUROPA.tilt) { return mul(rotZ(roll), rotX(tilt)); }

/* ── glyph atlas and the shape-matching lookup table ─────────────────── */
const FONT = '600 {}px ui-monospace, "SF Mono", Menlo, Consolas, monospace';
function drawAtlas(cw, ch) {
  const a = document.createElement("canvas"); a.width = NG * cw; a.height = ch;
  const x = /** @type {CanvasRenderingContext2D} */ (a.getContext("2d", { willReadFrequently: true }));
  x.fillStyle = "#000"; x.fillRect(0, 0, a.width, a.height);
  x.fillStyle = "#fff"; x.font = FONT.replace("{}", (cw / 0.602).toFixed(2));
  x.textAlign = "center"; x.textBaseline = "middle";
  for (let i = 0; i < NG; i++) {
    x.save(); x.beginPath(); x.rect(i * cw, 0, cw, ch); x.clip();
    x.fillText(String.fromCharCode(32 + i), i * cw + cw / 2, ch / 2 + ch * 0.03); x.restore();
  }
  return a;
}

/** Index into the lookup table of six quantised sub-cell samples (a b / d e / f g). */
export function lutIndex(qa, qb, qd, qe, qf, qg) { return qa + Q * (qb + Q * (qd + Q * (qe + Q * (qf + Q * qg)))); }

/** The lookup table from the glyphs' ink vectors (NG x 6, already normalised):
 *  every quantised 2x3 block maps to the glyph whose shape fits best. */
export function buildLUTFromVectors(vec) {
  const N = Q ** 6, LUT = new Uint8Array(N), s = new Float32Array(6);
  for (let i = 1; i < N; i++) {
    let r = i; for (let k = 0; k < 6; k++) { s[k] = (r % Q) / (Q - 1); r = (r / Q) | 0; }
    let best = 0, bd = 1e9;
    for (let g = 0; g < NG; g++) {
      let d = 0; const o = g * 6;
      for (let k = 0; k < 6; k++) { const e = s[k] - vec[o + k]; d += e * e; }
      if (d < bd) { bd = d; best = g; }
    }
    LUT[i] = best;
  }
  return LUT;
}

// Shape matching: every glyph is described by how much ink sits in each of its 2x3 sub-cells.
function glyphVectors() {
  const cw = 16, ch = 32, a = drawAtlas(cw, ch);
  const px = /** @type {CanvasRenderingContext2D} */ (a.getContext("2d")).getImageData(0, 0, a.width, a.height).data;
  const vec = new Float32Array(NG * 6); let peak = 0;
  for (let g = 0; g < NG; g++) for (let k = 0; k < 6; k++) {
    const x0 = g * cw + (k % 2) * 8, y0 = Math.floor(k / 2) * (ch / 3) | 0, y1 = (Math.floor(k / 2) + 1) * (ch / 3) | 0;
    let s = 0, n = 0;
    for (let y = y0; y < y1; y++) for (let x = x0; x < x0 + 8; x++) { s += px[(y * a.width + x) * 4]; n++; }
    vec[g * 6 + k] = s / n / 255; if (vec[g * 6 + k] > peak) peak = vec[g * 6 + k];
  }
  for (let i = 0; i < vec.length; i++) vec[i] = Math.min(1, vec[i] / (peak * 0.92));
  return vec;
}

/* One table for every instance: built once (about 50-100 ms), off the render path. */
/** @type {Uint8Array | null} */
let sharedLUT = null;
/** @type {Promise<Uint8Array> | null} */
let sharedLUTPromise = null;
/** The shared lookup table, built now if it is not built yet. */
export function glyphTable() { return (sharedLUT ||= buildLUTFromVectors(glyphVectors())); }
/** Resolves with the shared lookup table, built in an idle callback after first paint. */
export function prepareGlyphTable() {
  if (sharedLUT) return Promise.resolve(sharedLUT);
  return (sharedLUTPromise ||= new Promise((resolve, reject) => {
    const run = () => { try { resolve(glyphTable()); } catch (err) { sharedLUTPromise = null; reject(err); } };
    if (typeof window.requestIdleCallback === "function") window.requestIdleCallback(run, { timeout: 1200 });
    else requestAnimationFrame(() => setTimeout(run, 0));
  }));
}

/* ── texture: the true-colour map (brightness is albedo, the rest is hue) ── */
/** @param {{ width: number, height: number, data: ArrayLike<number> }} img RGBA pixels (ImageData or alike) */
export function prepareTexture(img) {
  const W = img.width, H = img.height, n = W * H, d = img.data;
  const alb = new Float32Array(n), gu = new Float32Array(n), gv = new Float32Array(n), rgb = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) {
    const R = d[i * 4] / 255, Gc = d[i * 4 + 1] / 255, B = d[i * 4 + 2] / 255;
    const mx = Math.max(R, Gc, B, 1e-3);
    alb[i] = Math.min(1, mx * 1.02 + 0.02); rgb[i * 3] = R / mx; rgb[i * 3 + 1] = Gc / mx; rgb[i * 3 + 2] = B / mx;
  }
  for (let y = 0; y < H; y++) {
    const stretch = 1 / Math.max(0.3, Math.cos((0.5 - (y + 0.5) / H) * Math.PI));
    const yu = Math.max(0, y - 1), yd = Math.min(H - 1, y + 1);
    for (let x = 0; x < W; x++) {
      gu[y * W + x] = (alb[y * W + (x + 1) % W] - alb[y * W + (x + W - 1) % W]) * stretch;
      gv[y * W + x] = alb[yu * W + x] - alb[yd * W + x];
    }
  }
  return { W, H, alb, gu, gv, rgb };
}

/* ── grid ──────────────────────────────────────────────────────────── */
/** The character grid for a square canvas `cssSize` CSS px across: cells
 *  1:2, about `cellCss` CSS px wide, twice as many columns as rows so the
 *  grid stays square, each cell rendered at `cw` x `ch` internal px
 *  (SUPERSAMPLE x the device resolution, never under 4 x 8). */
export function gridFor(cssSize, dpr = 1, cellCss = CELL_CSS) {
  const rows = Math.max(4, Math.round(cssSize / (cellCss * 2)));
  const cols = rows * 2;
  const cw = Math.max(4, Math.round((cssSize / cols) * dpr * SUPERSAMPLE)), ch = cw * 2;
  return { cols, rows, cw, ch, width: cols * cw, height: rows * ch };
}

/** Arrival time (s) of a cell: resolves outward from the centre, with some grain. */
export function arrivalDelay(i, cols, rows, cw, ch, radius) {
  const dx = (i % cols) - cols / 2, dy = ((i / cols) | 0) - rows / 2;
  return 0.1 + 1.05 * Math.min(1.3, Math.hypot(dx * cw, dy * ch) / radius) + 0.4 * hash(i * 101 + 9);
}

/* ── body: everything that does not change while the sphere merely spins ── */
function buildBody(G, cx, cy, R, squash, M, sun, tex) {
  const { SW, SH, sx, sy, cols } = G;
  const x0 = Math.max(0, Math.floor((cx - R) / sx) - 1), x1 = Math.min(SW - 1, Math.ceil((cx + R) / sx) + 1);
  const y0 = Math.max(0, Math.floor((cy - R) / sy) - 1), y1 = Math.min(SH - 1, Math.ceil((cy + R) / sy) + 1);
  const cap = Math.max(0, (x1 - x0 + 1) * (y1 - y0 + 1));
  const b = { n: 0, idx: new Int32Array(cap), cell: new Int32Array(cap), u0: new Float32Array(cap), row: new Int32Array(cap),
    l0: new Float32Array(cap), le: new Float32Array(cap), ln: new Float32Array(cap), a: new Float32Array(cap), cx, cy, R };
  const lm = applyT(M, sun), edge = R / Math.max(sx, sy);
  let n = 0;
  for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) {
    const X = ((x + 0.5) * sx - cx) / R, Y = -((y + 0.5) * sy - cy) / (R * squash), r2 = X * X + Y * Y;
    if (r2 >= 1) continue;
    const Z = Math.sqrt(1 - r2);
    const px = M[0] * X + M[3] * Y + M[6] * Z, py = M[1] * X + M[4] * Y + M[7] * Z, pz = M[2] * X + M[5] * Y + M[8] * Z;
    const lat = Math.asin(Math.max(-1, Math.min(1, py))), lon = Math.atan2(px, pz);
    const cl = Math.cos(lat), sl = Math.sin(lat), co = Math.cos(lon), so = Math.sin(lon);
    b.idx[n] = y * SW + x; b.cell[n] = ((y / 3) | 0) * cols + (x >> 1);
    b.u0[n] = lon / TAU + 0.5;
    b.row[n] = Math.min(tex.H - 1, ((0.5 - lat / Math.PI) * tex.H) | 0) * tex.W;
    b.l0[n] = lm[0] * px + lm[1] * py + lm[2] * pz;
    b.le[n] = lm[0] * co - lm[2] * so;
    b.ln[n] = -lm[0] * sl * so + lm[1] * cl - lm[2] * sl * co;
    b.a[n] = Math.min(1, (1 - Math.sqrt(r2)) * edge * 0.9 + 0.15);
    n++;
  }
  b.n = n; return b;
}

function shadeMoon(G, b, T, theta, K) {
  const W = T.W, sub = G.sub, { idx, cell, u0, row, l0, le, ln, a } = b, alb = T.alb, gu = T.gu, gv = T.gv;
  const off = theta / TAU, rgb = T.rgb, jR = G.jR, jG = G.jG, jB = G.jB, jN = G.jN;
  for (let i = 0, n = b.n; i < n; i++) {
    let u = u0[i] - off; u -= Math.floor(u);
    const fx = u * W, xa = fx | 0, f = fx - xa, xb = xa + 1 === W ? 0 : xa + 1, r = row[i];
    const h = alb[r + xa] * (1 - f) + alb[r + xb] * f;
    const g = l0[i] - K * ((gu[r + xa] * (1 - f) + gu[r + xb] * f) * le[i] + gv[r + xa] * ln[i]);
    // direct sun with soft relief, plus a whisper of Jupiter-shine on the night side
    const s = g > 0 ? Math.pow(g, 0.62) : 0;
    sub[idx[i]] = Math.min(1, h * (0.03 + s) * 1.25) * a[i];
    const c = cell[i], p = (r + xa) * 3;
    jR[c] += rgb[p]; jG[c] += rgb[p + 1]; jB[c] += rgb[p + 2]; jN[c]++;
  }
}

/* ── WebGL: one quad, a cell texture and a glyph atlas ───────────────── */
const VERT = `attribute vec2 p; varying vec2 uv;
  void main(){ uv = vec2(p.x*.5+.5, .5-p.y*.5); gl_Position = vec4(p,0.,1.); }`;
// The source's ink on black, as premultiplied colour on a transparent ground:
// black (no ink) is alpha 0, so the page shows through around and between glyphs.
const FRAG = `precision highp float;
  varying vec2 uv; uniform vec2 grid; uniform float ink; uniform sampler2D cells, atlas;
  void main(){
    vec2 g = uv*grid; vec2 f = fract(g);
    vec4 c = texture2D(cells, (floor(g)+.5)/grid);
    float gi = floor(c.a*255.+.5);
    float m = texture2D(atlas, vec2((gi+f.x)/${NG}., f.y)).r;
    vec3 col = min(c.rgb*(m*1.05 + .07)*ink, 1.);
    gl_FragColor = vec4(col, max(col.r, max(col.g, col.b)));
  }`;

/**
 * @param {HTMLCanvasElement} canvas square canvas, sized by CSS
 * @param {{ texture: ReturnType<typeof prepareTexture>, arrival?: boolean, still?: boolean,
 *   cellCss?: number, period?: number, ink?: number }} options arrival: assemble out of scrambled glyphs on
 *   start; still: draw one frame and do not spin (reduced motion)
 * @returns {{ start(): void, stop(): void, resize(): void, destroy(): void } | null} null without WebGL
 */
export function createAsciiMoon(canvas, options) {
  const tex = options.texture;
  const arrival = options.arrival !== false, still = Boolean(options.still);
  const cellCss = options.cellCss || CELL_CSS, period = options.period || EUROPA.period;
  /** @type {WebGLRenderingContext | null} */
  let gl = null;
  try { gl = canvas.getContext("webgl", { alpha: true, premultipliedAlpha: true, antialias: false, depth: false, stencil: false }); } catch { gl = null; }
  if (!gl || gl.isContextLost()) return null;
  const lose = () => gl?.getExtension("WEBGL_lose_context")?.loseContext();

  const prog = gl.createProgram();
  const shaders = [];
  const shader = (type, src) => {
    const s = /** @type {WebGLRenderingContext} */ (gl).createShader(type);
    if (!s || !gl || !prog) return false;
    gl.shaderSource(s, src); gl.compileShader(s); shaders.push(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) return false;
    gl.attachShader(prog, s); return true;
  };
  if (!prog || !shader(gl.VERTEX_SHADER, VERT) || !shader(gl.FRAGMENT_SHADER, FRAG)) { lose(); return null; }
  gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) { lose(); return null; }
  gl.useProgram(prog);
  const quad = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, quad);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
  const aP = gl.getAttribLocation(prog, "p"); gl.enableVertexAttribArray(aP); gl.vertexAttribPointer(aP, 2, gl.FLOAT, false, 0, 0);
  const makeTex = (unit) => {
    const g = /** @type {WebGLRenderingContext} */ (gl), t = g.createTexture();
    g.activeTexture(g.TEXTURE0 + unit); g.bindTexture(g.TEXTURE_2D, t);
    for (const [k, v] of [[g.TEXTURE_MIN_FILTER, g.NEAREST], [g.TEXTURE_MAG_FILTER, g.NEAREST],
      [g.TEXTURE_WRAP_S, g.CLAMP_TO_EDGE], [g.TEXTURE_WRAP_T, g.CLAMP_TO_EDGE]]) g.texParameteri(g.TEXTURE_2D, k, v);
    return t;
  };
  const textures = [makeTex(0), makeTex(1)];
  gl.uniform1i(gl.getUniformLocation(prog, "cells"), 0);
  gl.uniform1i(gl.getUniformLocation(prog, "atlas"), 1);
  const uGrid = gl.getUniformLocation(prog, "grid");
  gl.uniform1f(gl.getUniformLocation(prog, "ink"), options.ink || INK);

  const LUT = glyphTable();
  const M = viewMatrix(), sun = norm(EUROPA.sun), K = EUROPA.relief;
  let theta = EUROPA.theta, clock = 0, prev = -1, raf = 0, running = false, destroyed = false;
  let G = null, body = null, dirty = true, key = "";

  function resize() {
    if (destroyed || !gl) return;
    const css = canvas.clientWidth || canvas.getBoundingClientRect().width;
    if (!css) return;
    const dpr = window.devicePixelRatio || 1;
    const { cols, rows, cw, ch, width, height } = gridFor(css, dpr, cellCss);
    const next = `${cols}x${rows}@${cw}`;
    if (next === key) return;
    key = next;
    canvas.width = width; canvas.height = height;
    gl.viewport(0, 0, width, height);
    gl.uniform2f(uGrid, cols, rows);
    gl.activeTexture(gl.TEXTURE1);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, drawAtlas(cw, ch));
    const nc = cols * rows, SW = cols * 2, SH = rows * 3, radius = Math.min(width, height) * DISC;
    G = { cols, rows, nc, SW, SH, sx: cw / 2, sy: ch / 3, sub: new Float32Array(SW * SH), out: new Uint8Array(nc * 4),
      jR: new Float32Array(nc), jG: new Float32Array(nc), jB: new Float32Array(nc), jN: new Uint8Array(nc),
      rv: new Float32Array(nc) };
    for (let i = 0; i < nc; i++) G.rv[i] = arrival ? arrivalDelay(i, cols, rows, cw, ch, radius) : -1e9;
    dirty = true;
    if (running && still) draw(1e9);
  }

  function draw(t) {
    if (!G || !gl) return;
    if (dirty) { body = buildBody(G, canvas.width / 2, canvas.height / 2, Math.min(canvas.width, canvas.height) * DISC, 1, M, sun, tex); dirty = false; }
    const { cols, rows, SW, sub, out, jR, jG, jB, jN, rv } = G, Q1 = Q - 1;
    sub.fill(0); jR.fill(0); jG.fill(0); jB.fill(0); jN.fill(0);
    shadeMoon(G, body, tex, theta, K);
    for (let r = 0, c = 0; r < rows; r++) {
      for (let x = 0; x < cols; x++, c++) {
        const o = c * 4, base = r * 3 * SW + x * 2;
        let glyph = 0, R = 0, Gc = 0, B = 0;
        const a = sub[base], b = sub[base + 1], d = sub[base + SW], e = sub[base + SW + 1], f = sub[base + 2 * SW], g = sub[base + 2 * SW + 1];
        const sum = a + b + d + e + f + g;
        if (sum > 0.012) {
          const mx = Math.max(a, b, d, e, f, g), k = (mx < 0.3 ? 0.5 + 0.15 / Math.max(mx, 0.07) : 1) * Q1;   // let shape, not just tone, pick the glyph
          const qa = Math.min(Q1, a * k + 0.5 | 0), qb = Math.min(Q1, b * k + 0.5 | 0), qd = Math.min(Q1, d * k + 0.5 | 0),
                qe = Math.min(Q1, e * k + 0.5 | 0), qf = Math.min(Q1, f * k + 0.5 | 0), qg = Math.min(Q1, g * k + 0.5 | 0);
          glyph = LUT[lutIndex(qa, qb, qd, qe, qf, qg)];
          const avg = sum / 6, lift = Math.min(1, Math.pow(avg, 0.62) * 1.35 + 0.06);
          // the cell's hue from the colour map, scaled to the cell's brightness
          const hm = 255 / Math.max(jR[c], jG[c], jB[c], 1e-3), h0 = jN[c] ? jR[c] * hm : 255, h1 = jN[c] ? jG[c] * hm : 255, h2 = jN[c] ? jB[c] * hm : 255;
          const m = lift / Math.max(h0, h1, h2) * 255;
          R = h0 * m; Gc = h1 * m; B = h2 * m;
          // arrival: the moon assembles itself out of scrambled glyphs, each cell with a brief flash
          if (t < rv[c]) { const h = hash(c * 131 + ((t * 16) | 0) * 977); glyph = h > 0.45 ? 1 + ((h * 9973) % 94 | 0) : 0; const dim = 0.3 + 0.4 * h; R *= dim; Gc *= dim; B *= dim; }
          else if (t - rv[c] < 0.4) { const w = (1 - (t - rv[c]) / 0.4) * 110; R += w; Gc += w; B += w; }
        }
        out[o] = R > 255 ? 255 : R; out[o + 1] = Gc > 255 ? 255 : Gc; out[o + 2] = B > 255 ? 255 : B; out[o + 3] = glyph;
      }
    }
    gl.activeTexture(gl.TEXTURE0);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, cols, rows, 0, gl.RGBA, gl.UNSIGNED_BYTE, out);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  }

  function frame(now) {
    if (!running) return;
    raf = requestAnimationFrame(frame);
    const dt = prev < 0 ? 0 : Math.min(0.1, Math.max(0, (now - prev) / 1000));
    prev = now; clock += dt;
    theta = (theta + dt * TAU / period) % TAU;
    draw(clock);
  }

  function start() {
    if (running || destroyed) return;
    running = true; prev = -1;
    resize();
    if (still) draw(1e9);
    else raf = requestAnimationFrame(frame);
  }
  function stop() {
    running = false;
    if (raf) cancelAnimationFrame(raf);
    raf = 0;
  }

  return {
    start,
    stop,
    resize,
    destroy() {
      if (destroyed) return;
      stop();
      destroyed = true;
      const g = gl;
      if (g && !g.isContextLost()) {
        for (const t of textures) g.deleteTexture(t);
        g.deleteBuffer(quad);
        for (const s of shaders) { g.detachShader(prog, s); g.deleteShader(s); }
        g.deleteProgram(prog);
      }
      lose();
      gl = null; G = null; body = null;
    },
  };
}

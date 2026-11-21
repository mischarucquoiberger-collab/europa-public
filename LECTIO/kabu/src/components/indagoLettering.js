/* The thin, geometric, widely spaced lettering of the header: the EUROPA
 * wordmark and the Dashboard toggle labels ("Dashboard", "Close").
 *
 * Construction, in lettering units (u):
 *   - letter box y 67..113 (46 u); straight stems and bars are FILLED shapes
 *     8 u wide drawn with stroke 3 + round join (visual weight ~11 u, letters
 *     65.5..114.5 = 49 u tall);
 *   - curves are 10.5 u centre-line strokes (fill none) with ~9-10 u rounded
 *     corners, centre lines at y 71 / 109 (as O);
 *   - letter-spacing: ~41 u between straight or round sides, ~38 u next to a
 *     diagonal.
 * Every svg built from this module keeps a 64 u viewBox height band
 * (y 58..122, centred on y 90). */

const round = (n) => Math.round(n * 1000) / 1000;

/* Glyphs: d, the x its own coordinates start at (subtracted on placement),
 * the visual extent [left, right] relative to that start (stroke included),
 * whether it is a centre-line stroke, and whether a diagonal forms its
 * left/right side (tighter spacing there). */
const GLYPHS = {
  D: { d: "M216 67h44q14 0 14 13v20q0 13-14 13h-44zm8 7v32h36q7 0 7-7V81q0-7-7-7z", origin: 216, vis: [-1.5, 59.5], evenodd: true },
  A: { d: "m315 113 29-46h9l29 46h-9l-24.5-38-24.5 38z", origin: 315, vis: [-1.5, 68.5], diagL: true, diagR: true },
  O: { d: "M540 71h33q10 0 10 9v20q0 9-10 9h-33q-10 0-10-9V80q0-9 10-9Z", origin: 530, vis: [-5.25, 58.25], stroke: true },
  S: { d: "M53 71H10q-10 0-10 9.5q0 9.5 10 9.5h33q10 0 10 9.5q0 9.5-10 9.5H0", origin: 0, vis: [-5.25, 58.25], stroke: true },
  H: { d: "M0 67h8v19h40V67h8v46h-8V94H8v19H0z", origin: 0, vis: [-1.5, 57.5] },
  B: {
    d: "M0 67h40q13 0 13 11.5q0 11.5-13 11.5h3q13 0 13 11.5q0 11.5-13 11.5H0z" +
       "M8 74v12.5h31q6 0 6-6.25q0-6.25-6-6.25z" +
       "M8 93.5V106h34q6 0 6-6.25q0-6.25-6-6.25z",
    origin: 0, vis: [-1.5, 57.5], evenodd: true,
  },
  R: {
    d: "M0 113V67h40q13 0 13 13.25q0 13.25-11 13.25l13 19.5h-9.5l-13-19.5H8V113z" +
       "M8 74v12.5h31q6 0 6-6.25q0-6.25-6-6.25z",
    origin: 0, vis: [-1.5, 56.5], evenodd: true, diagR: true,
  },
  C: { d: "M54 71H9q-9 0-9 9v20q0 9 9 9h45", origin: 0, vis: [-5.25, 54], stroke: true },
  U: { d: "M0 65.5V100q0 9 10 9h33q10 0 10-9V65.5", origin: 0, vis: [-5.25, 58.25], stroke: true },
  P: {
    d: "M0 113V67h40q13 0 13 13.25q0 13.25-13 13.25H8V113z" +
       "M8 74v12.5h31q6 0 6-6.25q0-6.25-6-6.25z",
    origin: 0, vis: [-1.5, 54.5], evenodd: true,
  },
  L: { d: "M0 67h8v38h38v8H0z", origin: 0, vis: [-1.5, 47.5] },
  E: { d: "M0 67h46v8H8v11h36v8H8v11h38v8H0z", origin: 0, vis: [-1.5, 47.5] },
};

const GAP = 41;          // between straight or round sides
const GAP_DIAGONAL = 38; // next to a diagonal side
const PAD = 0.5;         // viewBox margin around the outermost stroke

/** Lays out a word in the lettering: its viewBox (y band 58..122) and one
 *  placed path per letter. */
export function letteringWord(word) {
  const paths = [];
  let cursor = 0;
  let prev = null;
  let left = 0;
  let right = 0;
  for (const ch of word.toUpperCase()) {
    const g = GLYPHS[ch];
    if (!g) throw new Error(`no glyph for ${ch}`);
    if (prev) cursor += prev.diagR || g.diagL ? GAP_DIAGONAL : GAP;
    else left = cursor;
    const start = cursor - g.vis[0];      // where the glyph's own x=0 lands
    paths.push({ d: g.d, dx: round(start - g.origin), stroke: !!g.stroke, evenodd: !!g.evenodd });
    cursor = start + g.vis[1];
    right = cursor;
    prev = g;
  }
  const x = round(left - PAD);
  const width = round(right - left + 2 * PAD);
  return { viewBox: `${x} 58 ${width} 64`, width, height: 64, paths };
}

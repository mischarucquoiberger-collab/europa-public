// Deep Research opening screen (owner 2026-10-13): the loading phase of the lusion.co preloader,
// 1:1 in look, geometry, timing and motion, written from scratch here (no Lusion code, shaders,
// fonts or images).
//
//   Loading: in place of lusion.co's centred bar, the CALLISTO lettering and DEEP RESEARCH (owner
//   2026-10-13: "instead of the line ... Deep Research with the logo, and it fills up"; the name
//   is Callisto since 2026-11-22), on the brand navy #0e1420: #2b364c, filling with #fff from the
//   left exactly as the bar's fill did; and a three-digit
//   counter bottom-left ("000" -> "100"). Both are driven by one number t:
//     t = 0.3 * percentToStart + 0.7 * percent
//   percent rises toward the loader's target at most 1 per second; percentToStart rises at most 4
//   per second, once the target is 1 (the workspace is ready), and never past the share of
//   lusion.co's start-up tasks done so far (fast to t ~ .86, then a crawl: 0.7 -> 1 takes ~0.9 s,
//   as measured there).
//   Done: t == 1 and the counter reads 100. The screen then ends with Osmo's curved wipe
//   (lib/curvedWipe.js, run by DrSplash.jsx); the "I" morph and the rotating reveal that used to
//   follow are gone (owner 2026-10-13: "take off the line thing").
//   The frame step is capped at 1/20 s, as on lusion.co.
// Pure functions only (relative imports only: runs under node --test).

/** Seconds: percent may rise by at most 1 per this long. */
export const MIN_PRELOAD_DURATION = 1;
/** The share of t that waits for the workspace to be ready (Lusion's init-to-start share). */
export const PERCENT_BETWEEN_INIT_AND_START = 0.3;
/** Seconds: that share fills in at least this long. */
export const MIN_DURATION_BETWEEN_INIT_AND_START = 0.25;
/** lusion.co's start-up tasks (taskManager.percent), as measured there (1440x900): when the
 *  target reaches 1 about INIT_TASKS_HEAD of them are done, and the rest finish at a steady rate
 *  over INIT_TASKS_S * (1 - head) s. With the 4/s cap above, t runs .7 -> .856 in 0.13 s, then
 *  crawls to 1 in 0.77 s (lusion.co: .70 -> .857, then 0.76 s at 0.0036 per frame). */
export const INIT_TASKS_HEAD = 0.44;
export const INIT_TASKS_S = 1.6;
/** The longest step one frame may take (s). */
export const MAX_DT = 1 / 20;
/** The canvas pixel ratio cap, the bar's largest unit (px), and its share of the width. */
export const MAX_DPR = 1.5;
export const MAX_UNIT = 42;
export const UNIT_PER_WIDTH = 30;
/** The canvas bleeds this many px past the right and bottom edges. */
export const BLEED = 2;
export const DIGITS = 3;
/** The colours: the ground layer (the brand navy, as on Home), the bar's track and the fill / mark. */
export const GROUND = '#0e1420';
export const TRACK = '#2b364c';
export const WHITE = '#fff';
/** The watchdog: LEAVE_WATCHDOG_MS after the workspace is ready, the screen goes unless its frames
 *  are still running (a frame within FRAMES_ALIVE_MS: the loading or the wipe is on its way, so
 *  it is not cut off, e.g. after a tab hidden at ready comes back); LEAVE_HARD_CAP_MS after ready it goes
 *  whatever the frames do. */
export const LEAVE_WATCHDOG_MS = 8_000;
export const FRAMES_ALIVE_MS = 1_000;
export const LEAVE_HARD_CAP_MS = 30_000;

export const saturate = (x) => Math.min(1, Math.max(0, x));
export const mix = (a, b, r) => a + (b - a) * r;

/** One frame's step in seconds: never negative, never more than MAX_DT. */
export function frameStep(ms) {
  const dt = Number(ms) / 1000;
  return Number.isFinite(dt) && dt > 0 ? Math.min(dt, MAX_DT) : 0;
}

/** The bar's unit (px) for a screen this wide. */
export function unitFor(width) {
  return Math.floor(Math.min(MAX_UNIT, Math.max(0, width) / UNIT_PER_WIDTH));
}

/** The canvas pixel ratio. */
export function canvasRatio(devicePixelRatio) {
  return Math.min(MAX_DPR, Number(devicePixelRatio) || 0) || 1;
}

/** The loader's progress as the preloader's target (0..1): the page's percent (it tops out at
 *  98) until the workspace is ready (or known to be absent from this build: 'offline'), then 1. */
export function percentTarget(phase, percent) {
  if (phase === 'ready' || phase === 'offline') return 1;
  return saturate((Number(percent) || 0) / 100);
}

/** A fresh preloader: nothing loaded, nothing started. */
export function createPreloader() {
  return {
    percentTarget: 0,
    percent: 0,
    percentToStart: 0,
    /** seconds since the target reached 1 (lusion.co's start-up tasks run meanwhile) */
    initTime: 0,
    /** t of the last step (the lockup's fill and the counter) */
    t: 0,
    eased: Array.from({ length: DIGITS }, () => 0),
    /** loading is over: t == 1 and the counter reads 100 (the wipe may start) */
    done: false,
  };
}

/** The share of lusion.co's start-up tasks done initTime s after the target reached 1. */
export function initTasks(initTime) {
  return saturate(INIT_TASKS_HEAD + Math.max(0, initTime) / INIT_TASKS_S);
}

/**
 * Advance the preloader by dt seconds (mutates and returns it).
 * target: the loader's progress (percentTarget()); frozen: an error is showing, so nothing moves
 * on (the fill holds, the digits only finish easing, and loading is never done meanwhile);
 * skip: reduced motion (Lusion's SKIP_ANIMATION: t reaches its value in one frame, and the
 * digits show their value at once).
 */
export function stepPreloader(state, dt, { target = 0, frozen = false, skip = false } = {}) {
  const s = state;
  if (s.done) return s;
  const go = frozen ? 0 : dt;
  if (!frozen) s.percentTarget = Math.max(s.percentTarget, saturate(target));
  const rise = frozen ? 0 : skip ? 1 : (s.percentTarget > s.percent ? go : 0) / MIN_PRELOAD_DURATION;
  s.percent = Math.min(s.percentTarget, s.percent + rise);
  if (s.percentTarget === 1 && !frozen) {
    s.initTime += go;
    s.percentToStart = skip
      ? 1
      : Math.min(initTasks(s.initTime), s.percentToStart + go / MIN_DURATION_BETWEEN_INIT_AND_START);
  }
  const t = s.percentToStart * PERCENT_BETWEEN_INIT_AND_START + s.percent * (1 - PERCENT_BETWEEN_INIT_AND_START);
  let counted = true;
  for (let a = 0; a < DIGITS; a++) {
    const value = columnTarget(t, a);
    s.eased[a] = skip ? value : easeColumn(s.eased[a], value, dt);
    if (s.eased[a] !== value) counted = false;
  }
  s.t = t;
  if (t === 1 && counted && !frozen) s.done = true;
  return s;
}

/**
 * The page reports its percent every 200 ms in whole numbers; fed straight in, the bar would
 * catch up in a frame and then wait (lusion.co's moves every frame). glideTarget() glides from
 * the value shown to each new report over the time the last report took (0.1-0.6 s), so the bar
 * moves every frame, one report behind. It never falls. Times in seconds.
 */
export const GLIDE_MIN_S = 0.1;
export const GLIDE_MAX_S = 0.6;
export const GLIDE_FIRST_S = 0.2;

export function createGlide() {
  return { from: 0, to: 0, start: 0, duration: GLIDE_FIRST_S, lastChange: null };
}

export function glideTarget(glide, reported, now) {
  const g = glide;
  const value = (at) => mix(g.from, g.to, saturate((at - g.start) / g.duration));
  const next = saturate(Number(reported) || 0);
  if (next > g.to) {
    const current = value(now);
    g.duration = g.lastChange == null
      ? GLIDE_FIRST_S
      : Math.min(GLIDE_MAX_S, Math.max(GLIDE_MIN_S, now - g.lastChange));
    g.from = current;
    g.to = next;
    g.start = now;
    g.lastChange = now;
  }
  return value(now);
}

/** What the watchdog does msSinceReady after ready, msSinceFrame after the last frame ran. */
export function watchdogAction(msSinceReady, msSinceFrame) {
  if (msSinceReady >= LEAVE_HARD_CAP_MS) return 'leave';
  if (msSinceReady < LEAVE_WATCHDOG_MS) return 'wait';
  return msSinceFrame < FRAMES_ALIVE_MS ? 'wait' : 'leave';
}

/** The value column a (0 = hundreds) eases toward: floor(t), floor(10 t), floor(100 t). They
 *  are cumulative, not mod 10, so the units column rolls through every digit up to 100. */
export function columnTarget(t, a) {
  return Math.floor((t * 100) / Math.pow(10, DIGITS - a - 1));
}

/** One frame of a column's easing toward its value (1 - e^(-7 dt)), snapped within 0.01. */
export function easeColumn(eased, value, dt) {
  const next = mix(eased, value, 1 - Math.exp(-7 * dt));
  return value - next < 0.01 ? value : next;
}

/** What a column shows: the current digit on top, the next below, the roll between them, and
 *  the column's transform (the roll up). */
export function digitColumn(eased) {
  const u = eased % 10;
  const top = Math.floor(u);
  const next = Math.ceil(u) % 10;
  const roll = u - top;
  return { top, next, roll, transform: `translateY(${roll ? -roll * 50 : 0}%) translateY(-0.05em)` };
}

/** The counter's text at t ("000", "068", "100"). */
export function counterText(t) {
  return String(Math.min(100, columnTarget(t, DIGITS - 1))).padStart(DIGITS, '0');
}

/** The lockup: the one word CALLISTO in the header's lettering (the paths of the Dashboard header's
 *  construction: filled letters carry a 3-unit outline, C / S / O are centre lines 10.5 wide). The
 *  view is the letters' visible box, outline included. */
export const WORDMARK_OUTLINE = 3;
export const WORDMARK_VIEW = Object.freeze({ x: -1.5, y: 65.5, w: 706.75, h: 49 });
/** @type {ReadonlyArray<{ ch: string, d: string, rule?: CanvasFillRule, stroke?: number }>} */
export const WORDMARK_PATHS = Object.freeze([
  Object.freeze({ ch: 'C', d: 'M57.75 71H12.75q-9 0-9 9v20q0 9 9 9h45', stroke: 10.5 }),
  Object.freeze({ ch: 'A', d: 'm98.75 113 29-46h9l29 46h-9l-24.5-38-24.5 38z' }),
  Object.freeze({ ch: 'L', d: 'M206.75 67h8v38h38v8H206.75z' }),
  Object.freeze({ ch: 'L', d: 'M296.75 67h8v38h38v8H296.75z' }),
  Object.freeze({ ch: 'I', d: 'M386.75 67h8v46h-8z' }),
  Object.freeze({ ch: 'S', d: 'M495.5 71H452.5q-10 0-10 9.5q0 9.5 10 9.5h33q10 0 10 9.5q0 9.5-10 9.5H442.5', stroke: 10.5 }),
  Object.freeze({ ch: 'T', d: 'M543.25 67h56v8H575.25v38h-8V75H543.25z' }),
  Object.freeze({ ch: 'O', d: 'M657 71h33q10 0 10 9v20q0 9-10 9h-33q-10 0-10-9V80q0-9 10-9Z', stroke: 10.5 }),
]);
/** The curved wipe's logo (owner 2026-11-22: the first screen says only CALLISTO, the swipe after
 *  it says just DEEP RESEARCH; 2026-10-13: "only Deep Research, simple and clear"): DEEP RESEARCH
 *  in Michroma (SIL OFL; self-hosted in src/assets/fonts), one filled
 *  <path> per letter, left to right, as the resource asks. The outlines are the font's own glyphs
 *  (units per em 2048, caps 1536 tall, tracking 0.12 em), drawn caps-on-baseline at y = 1536; the
 *  viewBox is the letters' box (round letters overshoot by 32). GSAP's yPercent takes each path's
 *  own box, so at 105% every letter starts below the box and at -130% ends above it. */
export const WIPE_LOGO_TEXT = 'DEEP RESEARCH';
export const WIPE_LOGO_VIEWBOX = '0 -32 27475 1600';
/** @type {ReadonlyArray<{ ch: string, d: string, rule?: CanvasFillRule }>} */
export const WIPE_LOGO_PATHS = Object.freeze([
  Object.freeze({ ch: 'D', d: 'M196 1536V0H1336Q1561 0 1706 27Q1851 54 1932.5 131.5Q2014 209 2046.5 357Q2079 505 2079 748V788Q2079 1023 2046.5 1170.5Q2014 1318 1932.5 1397.5Q1851 1477 1706 1506.5Q1561 1536 1336 1536ZM388 1370H1336Q1515 1370 1624 1353Q1733 1336 1790 1279Q1847 1222 1867 1105Q1887 988 1887 788V748Q1887 582 1875 474Q1863 366 1830.5 303.5Q1798 241 1736.5 211.5Q1675 182 1577 174Q1479 166 1336 166H388Z' }),
  Object.freeze({ ch: 'E', d: 'M2645 1536V0H4153V160H2837V672H4098V832H2837V1376H4181V1536Z' }),
  Object.freeze({ ch: 'E', d: 'M4683 1536V0H6191V160H4875V672H6136V832H4875V1376H6219V1536Z' }),
  Object.freeze({ ch: 'P', d: 'M6725 1536V0H7753Q7978 0 8115.5 22Q8253 44 8324 95.5Q8395 147 8420 234.5Q8445 322 8445 452V492Q8445 616 8419.5 702.5Q8394 789 8321 842Q8248 895 8110 919.5Q7972 944 7747 944H6917V1536ZM8253 452Q8253 357 8235 300Q8217 243 8163 214Q8109 185 8002 175.5Q7895 166 7716 166H6917V778H7716Q7895 778 8002 766.5Q8109 755 8163 724.5Q8217 694 8235 637.5Q8253 581 8253 492Z' }),
  Object.freeze({ ch: 'R', d: 'M9544 0H10572Q10797 0 10934.5 20Q11072 40 11143 89Q11214 138 11239 223Q11264 308 11264 438V478Q11264 598 11235.5 684.5Q11207 771 11126 824.5Q11045 878 10886 900L11220 1536H11028L10701 914Q10681 915 10659.5 915Q10638 915 10615 915H9736V1536H9544ZM9736 749H10585Q10756 749 10854.5 737.5Q10953 726 10999.5 697Q11046 668 11059 615Q11072 562 11072 478V438Q11072 343 11054 288Q11036 233 10982 207Q10928 181 10821 173.5Q10714 166 10535 166H9736Z' }),
  Object.freeze({ ch: 'E', d: 'M11873 1536V0H13381V160H12065V672H13326V832H12065V1376H13409V1536Z' }),
  Object.freeze({ ch: 'S', d: 'M15546 1092Q15546 1003 15532 952Q15518 901 15469 876.5Q15420 852 15317 844.5Q15214 837 15035 834L14479 826Q14273 823 14148 801Q14023 779 13959 731.5Q13895 684 13873.5 604Q13852 524 13852 404Q13852 273 13881.5 188Q13911 103 13988.5 55Q14066 7 14208 -12.5Q14350 -32 14575 -32H15003Q15207 -32 15343 -19Q15479 -6 15559 41Q15639 88 15673.5 187Q15708 286 15708 459H15516Q15516 325 15490.5 256.5Q15465 188 15406.5 163Q15348 138 15249 136Q15150 134 15003 134H14585Q14406 134 14298.5 141Q14191 148 14136 173Q14081 198 14062.5 253Q14044 308 14044 404Q14044 485 14057 534Q14070 583 14115.5 608.5Q14161 634 14256 643.5Q14351 653 14515 655L15111 663Q15321 666 15446.5 687.5Q15572 709 15634.5 757Q15697 805 15717.5 886.5Q15738 968 15738 1092Q15738 1227 15712.5 1318.5Q15687 1410 15614 1465Q15541 1520 15403 1544Q15265 1568 15040 1568H14572Q14367 1568 14228 1550Q14089 1532 14006.5 1477.5Q13924 1423 13888 1315Q13852 1207 13852 1027H14044Q14044 1168 14067 1245Q14090 1322 14147.5 1355.5Q14205 1389 14308.5 1395.5Q14412 1402 14572 1402H15030Q15209 1402 15313 1390.5Q15417 1379 15467 1346.5Q15517 1314 15531.5 1253Q15546 1192 15546 1092Z' }),
  Object.freeze({ ch: 'E', d: 'M16299 1536V0H17807V160H16491V672H17752V832H16491V1376H17835V1536Z' }),
  Object.freeze({ ch: 'A', d: 'M18209 1536 19105 0H19361L20257 1536H20033L19841 1184H18625L18433 1536ZM18721 1024H19745L19233 128Z' }),
  Object.freeze({ ch: 'R', d: 'M20763 0H21791Q22016 0 22153.5 20Q22291 40 22362 89Q22433 138 22458 223Q22483 308 22483 438V478Q22483 598 22454.5 684.5Q22426 771 22345 824.5Q22264 878 22105 900L22439 1536H22247L21920 914Q21900 915 21878.5 915Q21857 915 21834 915H20955V1536H20763ZM20955 749H21804Q21975 749 22073.5 737.5Q22172 726 22218.5 697Q22265 668 22278 615Q22291 562 22291 478V438Q22291 343 22273 288Q22255 233 22201 207Q22147 181 22040 173.5Q21933 166 21754 166H20955Z' }),
  Object.freeze({ ch: 'C', d: 'M23028 788V748Q23028 544 23048 405.5Q23068 267 23117 180Q23166 93 23250.5 47Q23335 1 23463 -15.5Q23591 -32 23771 -32H24174Q24380 -32 24521.5 -12.5Q24663 7 24749.5 64.5Q24836 122 24875 233.5Q24914 345 24914 529H24722Q24722 384 24696 303.5Q24670 223 24608.5 187Q24547 151 24441 142.5Q24335 134 24174 134H23771Q23628 134 23530 142.5Q23432 151 23370.5 181.5Q23309 212 23276.5 278Q23244 344 23232 458Q23220 572 23220 748V788Q23220 958 23232 1070Q23244 1182 23276.5 1249Q23309 1316 23370.5 1349Q23432 1382 23530 1392Q23628 1402 23771 1402H24174Q24335 1402 24441 1395Q24547 1388 24608.5 1354Q24670 1320 24696 1240.5Q24722 1161 24722 1017H24914Q24914 1201 24875 1311Q24836 1421 24749.5 1476.5Q24663 1532 24521.5 1550Q24380 1568 24174 1568H23771Q23546 1568 23401 1537.5Q23256 1507 23174.5 1425Q23093 1343 23060.5 1189Q23028 1035 23028 788Z' }),
  Object.freeze({ ch: 'H', d: 'M25487 1536V0H25679V672H27087V0H27279V1536H27087V832H25679V1536Z' }),
]);
/** No words beside the lettering (it was DEEP RESEARCH in Michroma). */
export const LOCKUP_TEXT = '';
export const LOCKUP_FONT = '"Michroma", "Helvetica Neue", Arial, sans-serif';
/** Michroma's cap height per em, letter spacing (em) and the gap between the two words (caps). */
export const CAP_RATIO = 0.7;
export const TRACKING = 0.16;
export const LOCKUP_GAP = 1.1;
/** The lockup's height (px) for the bar's unit N: 51 px on a desktop (the curved wipe's logo:
 *  11em * 180 / 622 at 16 px), never under 14 px. */
export function capHeightFor(unit) {
  return Math.min(51, Math.max(14, unit * 1.22));
}

/** The widest the lockup may be, as a share of the screen (the curved wipe's logo: 84vw). */
export const LOCKUP_SCREEN_SHARE = 0.84;

/** The least space (px) the lockup keeps from each side of the screen. */
export const LOCKUP_GUTTER = 16;

/**
 * The lockup's layout in px around the screen centre for the bar's unit N. measure(ch, fontPx)
 * returns the advance of one character. Returns the cap height, the lettering's scale (px per
 * viewBox unit), the font size, each letter's x, and the total width / left / top.
 * maxWidth: the widest the lockup may be. capHeightFor's 10 px floor makes it about 312 px wide
 * in Michroma, wider than a 320 px screen, so on a screen that narrow the cap shrinks to fit
 * (the mark, the gap and the text all scale with the cap).
 */
export function lockupLayout(unit, measure, maxWidth = Infinity) {
  const wanted = capHeightFor(unit);
  const atCap = layoutAtCap(wanted, measure);
  const limit = Number(maxWidth);
  if (!(limit < atCap.width)) return atCap;
  if (!(limit > 0) || !(atCap.width > 0)) return layoutAtCap(0, measure);
  const fitted = layoutAtCap(wanted * (limit / atCap.width), measure);
  // a measure that is not quite linear in the font size (hinting) gets one more step
  return fitted.width > limit ? layoutAtCap(fitted.cap * (limit / fitted.width), measure) : fitted;
}

function layoutAtCap(cap, measure) {
  const scale = cap / WORDMARK_VIEW.h;
  const markWidth = WORDMARK_VIEW.w * scale;
  const fontPx = cap / CAP_RATIO;
  const tracking = TRACKING * fontPx;
  const advances = [...LOCKUP_TEXT].map((ch) => Math.max(0, Number(measure(ch, fontPx)) || 0));
  // no words beside the lettering: no gap and no text width
  const gap = advances.length ? LOCKUP_GAP * cap : 0;
  const textWidth = advances.length ? advances.reduce((sum, w) => sum + w, 0) + tracking * (advances.length - 1) : 0;
  const width = markWidth + gap + textWidth;
  const left = -width / 2;
  const top = -cap / 2;
  const letters = [];
  let x = left + markWidth + gap;
  [...LOCKUP_TEXT].forEach((ch, k) => { letters.push({ ch, x }); x += advances[k] + tracking; });
  return { cap, scale, markWidth, fontPx, tracking, gap, textWidth, width, left, top, letters };
}

/** Draw the lockup in one colour, in px around the centre. */
function drawLockup(ctx, layout, color) {
  ctx.save();
  ctx.fillStyle = color;
  ctx.strokeStyle = color;
  if (typeof Path2D === 'function') {
    ctx.save();
    ctx.translate(layout.left, layout.top);
    ctx.scale(layout.scale, layout.scale);
    ctx.translate(-WORDMARK_VIEW.x, -WORDMARK_VIEW.y);
    WORDMARK_PATHS.forEach((path) => {
      const shape = new Path2D(path.d);
      if (path.stroke) {
        ctx.lineWidth = path.stroke;
        ctx.lineJoin = 'miter';
        ctx.stroke(shape);
      } else {
        ctx.fill(shape, path.rule || 'nonzero');
        ctx.lineWidth = WORDMARK_OUTLINE;       // the header lettering's outline
        ctx.lineJoin = 'round';
        ctx.stroke(shape);
      }
    });
    ctx.restore();
  }
  ctx.font = `400 ${layout.fontPx}px ${LOCKUP_FONT}`;
  ctx.textBaseline = 'alphabetic';
  ctx.textAlign = 'left';
  for (const { ch, x } of layout.letters) ctx.fillText(ch, x, layout.top + layout.cap);
  ctx.restore();
}

/**
 * Draw one frame of the overlay on a 2D context: the navy ground layer and the lockup, #2b364c filling
 * with #fff from the left by t.
 * width/height: the canvas's CSS size (the screen + BLEED); unit: unitFor(screen width); the
 * lockup keeps LOCKUP_GUTTER px from each side of the screen;
 * measure(ch, fontPx): a character's advance (defaults to the context's measureText).
 */
export function drawOverlay(ctx, { width, height, dpr = 1, unit, t = 0, measure = null }) {
  ctx.save();
  ctx.scale(dpr, dpr);
  ctx.globalCompositeOperation = 'source-over';
  ctx.globalAlpha = 1;
  ctx.fillStyle = GROUND;
  ctx.fillRect(0, 0, width, height);
  ctx.translate(width * 0.5, height * 0.5);
  const measureChar = measure || ((ch, fontPx) => {
    ctx.font = `400 ${fontPx}px ${LOCKUP_FONT}`;
    return ctx.measureText ? ctx.measureText(ch).width : fontPx * 0.8;
  });
  // the canvas is the screen plus BLEED: keep the lockup a gutter inside the screen's own width
  const screen = width - BLEED;
  const layout = lockupLayout(unit, measureChar, Math.min(screen - 2 * LOCKUP_GUTTER, screen * LOCKUP_SCREEN_SHARE));
  drawLockup(ctx, layout, TRACK);
  ctx.save();
  ctx.beginPath();
  ctx.rect(layout.left, layout.top - layout.cap, layout.width * saturate(t), layout.cap * 3);
  ctx.clip();
  drawLockup(ctx, layout, WHITE);
  ctx.restore();
  ctx.restore();
}

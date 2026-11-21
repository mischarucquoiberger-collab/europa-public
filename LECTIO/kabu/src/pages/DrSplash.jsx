import { useEffect, useRef, useState } from 'react';
import { openIndagoNavigation } from '@/lib/navigationEvents.js';
import {
  BLEED, DIGITS, FRAMES_ALIVE_MS, LEAVE_WATCHDOG_MS, WIPE_LOGO_PATHS, WIPE_LOGO_VIEWBOX, canvasRatio, createGlide, createPreloader,
  digitColumn, drawOverlay, frameStep, glideTarget, percentTarget, stepPreloader, unitFor, watchdogAction,
} from '@/lib/drSplashLusion.js';
import { runCurvedWipe, settleNext } from '@/lib/curvedWipe.js';
import { loaderStatus } from './dr2Loader.js';
import './DrSplash.css';

/* The Deep Research opening screen (owner 2026-10-13): the loading phase of the lusion.co
   preloader, 1:1 in look, geometry, timing and motion, in our own code (lib/drSplashLusion.js):
   the CALLISTO / DEEP RESEARCH lockup filling up and the "000"-"100" counter bottom-left follow the
   workspace's real progress. When the lockup is full and the counter reads 100, the screen ends
   with Osmo Supply's "Curved Wipe Page Transition", copied 1:1 (lib/curvedWipe.js, the resource's
   markup below): the panel rises over the screen with its curve while the logo letters slide up
   and the loading layer drifts up and goes; then the panel lifts off, the letters leave upward and
   the workspace rises in from below. Then onDone(). (The "I" morph and the rotating reveal that
   ended it before are gone, owner 2026-10-13.)

   The workspace frame loads underneath from the first moment, so the wipe shows the real
   workspace. In a build without the workspace service (phase 'offline') the screen plays out the
   same way and the wipe uncovers the page's offline notice ([data-testid="dr2-offline"]) instead. The loader's status is read to screen readers only; the errors with their Retry and
   the slow-start actions come from the page's loader (dr2Loader.js), unchanged. */

function prefersReducedMotion() {
  try {
    return typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true;
  } catch {
    return false;
  }
}

const COLUMNS = Array.from({ length: DIGITS }, (_, a) => a);

/**
 * phase: the workspace's ('checking' | 'opening' | 'ready' | 'offline' | 'error'); view: loaderView();
 * 'offline' (no workspace service in this build) ends the screen exactly as 'ready' does;
 * error / autoIn: the error text and the seconds before it retries by itself (or null);
 * onDone(): the screen has gone (the page then unmounts it).
 */
export default function DrSplash({ phase, view, error = '', autoIn = null, onRetry, onDone }) {
  const rootRef = useRef(null);
  // the loading layer: the wipe's "current" page
  const layerRef = useRef(null);
  const canvasRef = useRef(null);
  const preloaderRef = useRef(null);
  const columnRefs = useRef([]);
  // the loading bar up the left edge (owner 2026-11-22): its fill
  const railFillRef = useRef(null);
  const failed = phase === 'error';
  // no workspace service in this build: the screen still plays through and leaves, as on ready
  const ready = phase === 'ready' || phase === 'offline';
  // Decided once per open (a remount after Retry decides again).
  const [reduced] = useState(prefersReducedMotion);
  const shown = ready ? { ...view, percent: 100, step: 3, eta: 'Ready', slow: false } : view;

  // What the frame loop reads: the latest props, without restarting the loop.
  const live = useRef(/** @type {{ target: number, ready: boolean, failed: boolean, onDone?: () => void }} */ ({ target: 0, ready: false, failed: false }));
  live.current = { target: percentTarget(phase, view?.percent), ready, failed, onDone };
  const finishedRef = useRef(false);
  const finish = () => {
    if (finishedRef.current) return;
    finishedRef.current = true;
    // gone: nothing here takes the pointer any more (the notice keeps its own)
    rootRef.current?.setAttribute('data-done', '');
    live.current.onDone?.();
  };
  // when the frame loop last ran (the watchdog leaves it be while it does)
  const lastFrameRef = useRef(0);

  // The frame loop: one preloader per open (kept across React StrictMode's effect replay).
  const stateRef = useRef(null);
  const glideRef = useRef(null);
  // the running wipe: { entered (its enter Promise, with revert()), next, settled }
  const wipeRef = useRef(null);
  useEffect(() => {
    const root = rootRef.current;
    const layer = layerRef.current;
    const canvas = canvasRef.current;
    const preloader = preloaderRef.current;
    if (!root || !layer || !canvas || !preloader) return undefined;
    if (!stateRef.current) stateRef.current = createPreloader();
    if (!glideRef.current) glideRef.current = createGlide();
    const state = stateRef.current;
    const glide = glideRef.current;
    let ctx = null;
    try { ctx = canvas.getContext('2d'); } catch { ctx = null; }
    // the lockup's face (index.css); the canvas redraws every frame, so it switches as it lands
    try { document.fonts?.load?.('400 16px Michroma')?.catch?.(() => {}); } catch { /* no font API */ }
    let raf = 0;
    let last = performance.now();
    let size = { w: -1, h: -1, dpr: 0 };
    const columns = columnRefs.current.map((el) => (el ? { el, nums: el.children } : null));

    const resize = () => {
      const w = root.clientWidth;
      const h = root.clientHeight;
      const dpr = canvasRatio(window.devicePixelRatio);
      if (w === size.w && h === size.h && dpr === size.dpr) return;
      size = { w, h, dpr };
      canvas.width = Math.round((w + BLEED) * dpr);
      canvas.height = Math.round((h + BLEED) * dpr);
      canvas.style.width = `${w + BLEED}px`;
      canvas.style.height = `${h + BLEED}px`;
    };

    const paint = () => {
      for (let a = 0; a < columns.length; a++) {
        const column = columns[a];
        if (!column) continue;
        const digit = digitColumn(state.eased[a]);
        const [top, next] = column.nums;
        if (top?.firstChild) top.firstChild.nodeValue = String(digit.top);
        if (next?.firstChild) next.firstChild.nodeValue = String(digit.next);
        column.el.style.transform = digit.transform;
      }
      // the bar: the same number the counter reads, every frame (a transform only)
      if (railFillRef.current) railFillRef.current.style.transform = `scaleY(${state.t})`;
      if (!ctx) return;
      resize();
      drawOverlay(ctx, {
        width: size.w + BLEED, height: size.h + BLEED, dpr: size.dpr, unit: unitFor(size.w), t: state.t,
      });
      canvas.style.display = 'block';
      // the canvas paints the navy ground from now on (Lusion's html.is-ready)
      preloader.setAttribute('data-ready', '');
    };

    // Loading is over (t == 1, the counter at 100): the curved wipe, once. current = the loading
    // layer; next = the workspace beside the splash (a stand-in if it is not there, so GSAP never
    // gets null). The resource ends the leave with current.remove(): this layer is React's, so
    // its own remove() only hides it.
    const startWipe = () => {
      const next = root.parentElement?.querySelector('[data-indago-surface="dr2"], [data-testid="dr2-offline"]')
        || document.createElement('div');
      layer.remove = () => { layer.style.visibility = 'hidden'; };
      root.setAttribute('data-wipe', '');
      const wipe = { entered: runCurvedWipe(layer, next), next, settled: false };
      wipeRef.current = wipe;
      wipe.entered.then(() => {
        if (wipeRef.current !== wipe) return;
        wipe.settled = true;
        settleNext(next);
        finish();
      });
    };

    const frame = (now) => {
      const dt = frameStep(now - last);
      last = now;
      lastFrameRef.current = performance.now();
      if (finishedRef.current) return;
      // while the wipe runs the loop only keeps the watchdog's heartbeat
      if (!wipeRef.current) {
        const { target: reported, ready: isReady, failed: frozen } = live.current;
        // the page's 200 ms reports, glided so the bar moves every frame; ready is 1 at once
        const target = isReady || reduced ? reported : glideTarget(glide, reported, now / 1000);
        stepPreloader(state, dt, { target, frozen, skip: reduced });
        paint();
        if (state.done) startWipe();
      }
      raf = window.requestAnimationFrame(frame);
    };
    raf = window.requestAnimationFrame(frame);
    return () => {
      window.cancelAnimationFrame(raf);
      // unmounted (or the effect replayed) mid-wipe: stop it and put the workspace back as it was
      const wipe = wipeRef.current;
      wipeRef.current = null;
      if (wipe && !wipe.settled) {
        wipe.entered.revert();
        root.removeAttribute('data-wipe');
        layer.style.visibility = '';
      }
    };
    // the loop reads the live props through `live`: it runs once per open
  }, [reduced]);

  // Never stuck: LEAVE_WATCHDOG_MS after the workspace is ready the screen goes if its frames have
  // stopped (a hidden tab); while they still run (a tab that came back late, a slow device) the
  // animation is left to finish, up to LEAVE_HARD_CAP_MS (lib/drSplashLusion.js watchdogAction).
  useEffect(() => {
    if (!ready) return undefined;
    const readyAt = performance.now();
    let timer = 0;
    const check = () => {
      const now = performance.now();
      if (watchdogAction(now - readyAt, now - lastFrameRef.current) === 'leave') finish();
      else timer = window.setTimeout(check, FRAMES_ALIVE_MS);
    };
    timer = window.setTimeout(check, LEAVE_WATCHDOG_MS);
    return () => window.clearTimeout(timer);
  }, [ready]);

  const status = loaderStatus(shown);
  const percent = Math.max(0, Math.min(100, Math.round(shown.percent)));
  return (
    <div
      ref={rootRef}
      className={`dr2-splash${failed ? ' is-failed' : ''}`}
      data-testid="dr2-loader"
      data-step={shown.step}
    >
      <h1 className="dr2-splash__sr">Callisto</h1>
      <div ref={layerRef} className="dr2-splash__layer" aria-hidden="true">
        <canvas ref={canvasRef} className="dr2-splash__overlay" />
        <div ref={preloaderRef} className="dr2-splash__preloader">
          <div className="dr2-splash__rail">
            <div ref={railFillRef} className="dr2-splash__rail-fill" />
          </div>
          <div className="dr2-splash__digits">
            {COLUMNS.map((a) => (
              <div key={a} ref={(el) => { columnRefs.current[a] = el; }} className="dr2-splash__digit">
                <div className="dr2-splash__digit-num">0</div>
                <div className="dr2-splash__digit-num">0</div>
              </div>
            ))}
          </div>
        </div>
      </div>
      {/* Osmo's curved wipe: the resource's markup 1:1, with DEEP RESEARCH as its logo */}
      <div data-transition-wrap="" className="transition" aria-hidden="true">
        <div data-transition-panel="" className="transition__panel">
          <div data-transition-panel-top="" className="transition__panel-top">
            <div className="transition__panel-circle"></div>
          </div>
          <div data-transition-panel-bottom="" className="transition__panel-bottom">
            <div className="transition__panel-circle"></div>
          </div>
        </div>
        <div data-transition-logo="" className="transition__logo">
          <svg xmlns="http://www.w3.org/2000/svg" width="100%" viewBox={WIPE_LOGO_VIEWBOX} fill="none" aria-hidden="true" focusable="false">
            {WIPE_LOGO_PATHS.map((path) => (
              <path key={`${path.ch}-${path.d.length}-${path.d.slice(0, 12)}`} d={path.d} fill="currentColor" fillRule={path.rule} />
            ))}
          </svg>
        </div>
      </div>
      {failed ? (
        <div className="dr2-splash__notice">
          <div role="alert">
            <p className="dr2-splash__notice-title">
              {autoIn != null ? 'Callisto is not open yet' : 'Unable to open Callisto'}
            </p>
            <p>{error}</p>
            {autoIn != null ? (
              <p data-testid="dr2-auto-retry" aria-live="polite">
                {`Trying again by itself in ${autoIn} s…`}
              </p>
            ) : null}
          </div>
          <div className="dr2-splash__actions">
            <button type="button" className="dr2-splash__button" onClick={onRetry}>Try again</button>
            <button type="button" className="dr2-splash__button" onClick={(event) => openIndagoNavigation(event.currentTarget)}>
              Dashboard
            </button>
          </div>
        </div>
      ) : (
        <>
          <p className="dr2-splash__sr" aria-live="polite" data-testid="dr2-loader-status">{status}</p>
          <div
            className="dr2-splash__sr"
            role="progressbar"
            aria-label="Opening Callisto"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={percent}
            aria-valuetext={`${percent}% — ${status}`}
          />
          {shown.slow ? (
            <div className="dr2-splash__notice">
              <div className="dr2-splash__actions">
                <button type="button" className="dr2-splash__button" onClick={onRetry}>Try again now</button>
                <button type="button" className="dr2-splash__button" onClick={(event) => openIndagoNavigation(event.currentTarget)}>
                  Dashboard
                </button>
              </div>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}

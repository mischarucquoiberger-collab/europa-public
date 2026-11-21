import { DEEP_RESEARCH_ENABLED } from '@/lib/features';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { createBrowserStorage } from '@/lib/browserStorage';
import {
  DR_ROUTE, buildDrFrameSrc, buildDrReportSrc, clearDrPrefill, drBackAction, drHistoryIdx, drPrefillAction,
  drPrefillByMessage, drTargetKey, isDrReportTarget, parseDrTarget, readDrPrefill,
} from '@/lib/drRoutes.js';
import { OPEN_INDAGO_NAVIGATION, isWorkspaceNavigationRequest, openIndagoNavigation } from '@/lib/navigationEvents.js';
import DrReadyNotifier from '@/components/DrReadyNotifier.jsx';
import DeepResearchMemoryDrawer from '@/components/DeepResearchMemoryDrawer.jsx';
import { inspectWorkspaceFrame } from './xyzWorkspace.js';
import {
  MAX_AUTO_REMOUNTS, WARMUP_ESTIMATE_MS, autoRemountLeft, classifyFrame, classifyStatus, estimateMs,
  frameSignals, isStalled, isWarmup, loaderView, awaitingReload, markReload, readOpenProfile, recordOpen, retryDelay,
  startingStalled, trackProgress,
} from './dr2Loader.js';
import { syncThreadToAddress } from './drThreadSync.js';
import { ArrowUp } from 'lucide-react';
import { WORDMARK_OUTLINE, WORDMARK_PATHS, WORDMARK_VIEW } from '@/lib/drSplashLusion.js';
import DrSplash from './DrSplash.jsx';
import { installPriceHistoryBridge } from '@/lib/priceHistoryBridge.js';
import './DeepResearch2.css';

const STATUS_TIMEOUT_MS = 15_000;      // per attempt; a busy core is retried with backoff
const MAX_AUTO_RETRIES = 1;
const RETRY_SETTLE_MS = 1_500;
// how often the address follows the chat the frame shows (reload restore)
const THREAD_SYNC_MS = 500;

function storage() {
  try { return window.localStorage; } catch { return null; }
}

const UNAVAILABLE = 'Callisto is unavailable right now. Please try again.';
const WARMUP_UNAVAILABLE = 'Callisto is still starting up after an update.';
const SESSION_ERROR = 'Callisto could not connect to your session. Return to the dashboard and try again.';

function initializeAppearance() {
  try {
    // Deep Research and its embedded chat share an origin. Set the native theme before
    // mounting the iframe, migrating the previous gray default only once.
    if (localStorage.getItem('indago_xyz_theme_revision') !== 'black-v1'
        || localStorage.getItem('color-theme') == null) {
      localStorage.setItem('color-theme', 'high-contrast-dark');
      localStorage.setItem('indago_xyz_theme_revision', 'black-v1');
    }
  } catch { /* Unavailable preference storage must not prevent opening Deep Research. */ }
}

function Workspace({ src, prefill = '', onPrefillTaken, onRetry, onAutoRetry = null, onThread = null, onSplashChange = null }) {
  // the native theme is set before the frame is first rendered (it now loads in parallel with the session check)
  useState(() => { initializeAppearance(); return true; });
  const frameRef = useRef(null);
  const prefillRef = useRef(prefill);
  const takenRef = useRef(onPrefillTaken);
  const [phase, setPhase] = useState('checking');
  const [error, setError] = useState('');
  const startedRef = useRef(performance.now());
  const profileRef = useRef(readOpenProfile(storage()));
  const estimateRef = useRef(estimateMs(profileRef.current));
  const retriesRef = useRef(0);
  const retryAtRef = useRef(Number.NEGATIVE_INFINITY);   // no retry has happened yet
  const shownRef = useRef(0);
  const [view, setView] = useState(() => loaderView({
    phase: 'checking', elapsed: 0, estimate: estimateRef.current, signals: null,
    expected: profileRef.current.resources,
  }));
  // the opening screen stays until its arrival has played and it has faded into the frame
  const [splashDone, setSplashDone] = useState(false);
  const signalsRef = useRef({ resources: 0, failed: 0, complete: false });
  const progressRef = useRef(null);          // last real progress of the frame (stall clock)
  const frameRetriesRef = useRef(0);
  const reloadTimerRef = useRef(null);
  const pendingReloadRef = useRef(null);
  const phaseRef = useRef('checking');
  phaseRef.current = phase;
  const warmupRef = useRef(false);           // the server restarted minutes ago (status uptime_s)
  const startingSinceRef = useRef(null);     // the document is in; waiting for the composer since
  const errorAtRef = useRef(null);
  const [autoIn, setAutoIn] = useState(null);

  // the screen ticks on its own while the session is being checked
  useEffect(() => {
    if (phase === 'ready' || phase === 'error' || phase === 'offline') return undefined;
    const tick = setInterval(() => {
      const retrying = performance.now() - retryAtRef.current < RETRY_SETTLE_MS * 2;
      const next = loaderView({
        phase, elapsed: performance.now() - startedRef.current, estimate: estimateRef.current,
        signals: signalsRef.current, expected: profileRef.current.resources, retrying, warmup: warmupRef.current,
      });
      // never let the bar move backwards
      shownRef.current = Math.max(shownRef.current, next.percent);
      setView({ ...next, percent: shownRef.current });
    }, 200);
    return () => clearInterval(tick);
  }, [phase]);

  // Reload restore: the address follows the chat the frame shows (#/DeepResearch?thread=…),
  // by replaceState only (no remount, no new history entry); a reload reopens that chat.
  const onThreadRef = useRef(onThread);
  useEffect(() => { onThreadRef.current = onThread; }, [onThread]);
  useEffect(() => {
    if (phase !== 'ready') return undefined;
    let last = null;
    const sync = () => {
      const thread = syncThreadToAddress(frameRef.current);
      if (thread != null && thread !== last) {
        last = thread;
        onThreadRef.current?.(thread);
      }
    };
    sync();
    const timer = setInterval(sync, THREAD_SYNC_MS);
    return () => clearInterval(timer);
  }, [phase]);

  useEffect(() => { prefillRef.current = prefill; takenRef.current = onPrefillTaken; }, [prefill, onPrefillTaken]);

  // A Query question too long for the frame URL: hand it to the composer once the
  // frame says it is listening; drop it when the frame confirms it was applied.
  // Fill only, never submit (the Confirm Deep Research card still gates a run).
  useEffect(() => {
    const onPrefillMessage = (event) => {
      const action = drPrefillAction(event, frameRef.current?.contentWindow, window.location.origin, prefillRef.current);
      if (action?.send) {
        try { event.source.postMessage(action.send, window.location.origin); } catch { /* the frame went away; its next document asks again */ }
      } else if (action?.taken) {
        prefillRef.current = '';
        takenRef.current?.();
      }
    };
    window.addEventListener('message', onPrefillMessage);
    return () => window.removeEventListener('message', onPrefillMessage);
  }, []);

  useEffect(() => {
    const openNavigation = (event) => {
      const frame = frameRef.current;
      if (!isWorkspaceNavigationRequest(event, frame, window.location.origin)) return;
      openIndagoNavigation(frame.contentDocument?.querySelector('[data-testid="xyz-dashboard-link"]') || frame);
    };
    window.addEventListener('message', openNavigation);
    return () => window.removeEventListener('message', openNavigation);
  }, []);

  useEffect(() => {
    let disposed = false;
    let controller = null;
    let wait = null;
    async function connect(attempt) {
      controller = new AbortController();
      const deadline = setTimeout(() => controller.abort(), STATUS_TIMEOUT_MS);
      const outcome = { status: 0, ready: false, aborted: false, json: true, failed: false };
      try {
        const response = await fetch('/api/xyz/status', {
          signal: controller.signal,
          cache: 'no-store',
          headers: { Accept: 'application/json' },
        });
        outcome.status = response.status;
        if (response.ok) {
          let body = null;
          try {
            body = await response.json();
          } catch {
            // a body that is not JSON (a dev server's HTML shell): no workspace service here
            if (controller.signal.aborted) outcome.aborted = true;
            else outcome.json = false;
          }
          outcome.ready = body?.ready === true;
          if (isWarmup(body?.uptime_s)) {
            // honest estimate: right after an update the app needs about a minute
            warmupRef.current = true;
            estimateRef.current = Math.max(estimateRef.current, WARMUP_ESTIMATE_MS);
          }
        }
      } catch {
        outcome.aborted = controller.signal.aborted;
        // the request failed outright (not our own timeout): no workspace service to reach
        outcome.failed = !outcome.aborted;
      } finally {
        clearTimeout(deadline);
      }
      // the frame loads in parallel: once it shows the composer, the check no longer matters
      if (disposed || phaseRef.current === 'ready') return;
      const verdict = classifyStatus(outcome);
      if (verdict === 'ok') { setPhase((now) => (now === 'checking' ? 'opening' : now)); return; }
      if (verdict === 'session') { setError(SESSION_ERROR); setPhase('error'); return; }
      // no workspace service in this build: the opening screen plays out over the offline notice
      if (verdict === 'offline') { setPhase('offline'); return; }
      // busy / starting / hung: retry with backoff before saying anything failed
      const delay = retryDelay(attempt);
      if (delay == null) { setError(warmupRef.current ? WARMUP_UNAVAILABLE : UNAVAILABLE); setPhase('error'); return; }
      retryAtRef.current = performance.now() + delay;     // "retrying…" while waiting
      wait = setTimeout(() => connect(attempt + 1), delay);
    }
    connect(0);
    return () => {
      disposed = true;
      clearTimeout(wait);
      controller?.abort();
    };
  }, []);

  useEffect(() => {
    if (phase !== 'opening' && phase !== 'checking') return undefined;
    function inspect() {
      const frame = frameRef.current;
      const signals = frameSignals(frame);
      signalsRef.current = signals;
      const result = inspectWorkspaceFrame(frame, window.location.origin);
      if (result === 'ready') {
        // a startup after an update is not this browser's usual open time
        if (!warmupRef.current) {
          profileRef.current = recordOpen(
            storage(), profileRef.current, performance.now() - startedRef.current, signals.resources,
          );
        }
        setPhase('ready');
        return;
      }
      // while the session is checked the frame only loads; the check decides first
      if (phase === 'checking') return;
      const now = performance.now();
      let current = null;
      try { current = frame?.contentDocument || null; } catch { /* cross-origin */ }
      // a reload is in flight: the old (503) document is still showing, do not re-classify it
      if (awaitingReload(pendingReloadRef.current, current, now)) return;
      pendingReloadRef.current = null;
      progressRef.current = trackProgress(progressRef.current, signals, now);
      if (signals.complete && startingSinceRef.current == null) startingSinceRef.current = now;
      const verdict = classifyFrame(result);
      if (verdict === 'session') {
        setError(SESSION_ERROR);
        setPhase('error');
        return;
      }
      // no progress for a minute, or the page is in but the composer never came
      const stalled = isStalled(progressRef.current, now)
        || startingStalled(startingSinceRef.current, now, { warmup: warmupRef.current, attempt: frameRetriesRef.current });
      if (verdict === 'retry' || stalled) {
        // a JSON 503 from a busy core, or no progress for a minute: reload the frame
        // with backoff; only when the retries are spent is the error shown
        if (reloadTimerRef.current) return;
        const delay = retryDelay(frameRetriesRef.current);
        if (delay == null) {
          setError(warmupRef.current ? WARMUP_UNAVAILABLE : stalled
            ? 'Callisto is taking longer than expected to open.'
            : UNAVAILABLE);
          setPhase('error');
          return;
        }
        frameRetriesRef.current += 1;
        retryAtRef.current = now + delay;
        reloadTimerRef.current = setTimeout(() => {
          reloadTimerRef.current = null;
          progressRef.current = null;
          startingSinceRef.current = null;
          let before = null;
          try { before = frame.contentDocument || null; } catch { /* cross-origin */ }
          pendingReloadRef.current = markReload(before, performance.now());
          try { frame.contentWindow.location.reload(); } catch {
            try { frame.src = frame.getAttribute('src'); } catch { /* the next tick retries */ }
          }
        }, delay);
        return;
      }
      // A script chunk the server failed to send (a busy or restarting server)
      // leaves the app unable to start: reload the frame once instead of waiting.
      const settled = performance.now() - retryAtRef.current > RETRY_SETTLE_MS;
      if (signals.failed > 0 && signals.complete && settled && retriesRef.current < MAX_AUTO_RETRIES) {
        retriesRef.current += 1;
        retryAtRef.current = performance.now();
        startingSinceRef.current = null;
        try { frame.contentWindow.location.reload(); } catch { /* the deadline below still applies */ }
      }
    }
    const interval = setInterval(inspect, 250);
    inspect();
    return () => {
      clearInterval(interval);
      clearTimeout(reloadTimerRef.current);
      reloadTimerRef.current = null;
    };
  }, [phase]);

  // No dead end: when every retry is spent, try again by itself after a short wait.
  useEffect(() => {
    if (phase !== 'error') { errorAtRef.current = null; setAutoIn(null); return undefined; }
    if (!onAutoRetry) return undefined;
    errorAtRef.current = performance.now();
    const left = () => autoRemountLeft({
      errorAt: errorAtRef.current, now: performance.now(), remountsUsed: 0, sessionError: error === SESSION_ERROR,
    });
    setAutoIn(left());
    if (left() == null) return undefined;
    const tick = setInterval(() => {
      const value = left();
      setAutoIn(value);
      if (value === 0) { clearInterval(tick); onAutoRetry(); }
    }, 250);
    return () => clearInterval(tick);
  }, [phase, error, onAutoRetry]);

  const ready = phase === 'ready';
  const offline = phase === 'offline';
  // covered by the opening screen until it has faded out: not yet focusable or announced
  const shown = ready && splashDone;
  const splashUp = !splashDone || phase === 'error';
  useEffect(() => { onSplashChange?.(splashUp); }, [splashUp, onSplashChange]);
  return (
    <div className="dr2-workspace__content" aria-busy={phase === 'checking' || phase === 'opening'}>
      {phase === 'checking' || phase === 'opening' || ready ? (
        <iframe
          ref={frameRef}
          className={`dr2-workspace__frame${ready ? ' is-ready' : ''}`}
          src={src}
          data-indago-surface="dr2"
          data-indago-auth-frame="research"
          title="Callisto workspace"
          allow="microphone; camera; clipboard-read; clipboard-write; fullscreen"
          tabIndex={shown ? 0 : -1}
          aria-hidden={!shown}
          onError={() => { setError(UNAVAILABLE); setPhase('error'); }}
        />
      ) : null}
      {offline ? <WorkspaceOffline hidden={!splashDone} /> : null}
      {!splashDone || phase === 'error' ? (
        <DrSplash
          phase={phase}
          view={view}
          error={error}
          autoIn={autoIn}
          onRetry={onRetry}
          onDone={() => setSplashDone(true)}
        />
      ) : null}
    </div>
  );
}

/* No workspace service in this build (phase 'offline'): the Deep Research landing on the navy
   ground, in place of the frame: the CALLISTO lettering and the question box. Nothing is sent
   anywhere (there is no research service to send to), and the line under the box says so.
   `hidden` keeps it out of the accessibility tree and out of reach while the opening screen
   still covers it. */
function WorkspaceOffline({ hidden = false }) {
  const [question, setQuestion] = useState('');
  const [tried, setTried] = useState(false);
  const boxRef = useRef(null);
  const filled = question.trim().length > 0;
  const fit = () => {
    const box = boxRef.current;
    if (!box) return;
    box.style.height = 'auto';
    box.style.height = `${Math.min(box.scrollHeight, 220)}px`;
  };
  const submit = (event) => {
    event.preventDefault();
    if (filled) setTried(true);
  };
  return (
    <div className="dr2-offline" data-testid="dr2-offline" aria-hidden={hidden || undefined}>
      <h2 className="dr2-offline__sr">Callisto</h2>
      {/* the page header stays out of the way on Deep Research: this is the way to the menu */}
      <button
        type="button"
        className="dr2-offline__menu"
        disabled={hidden}
        onClick={(event) => openIndagoNavigation(event.currentTarget)}
      >
        Dashboard
      </button>
      <svg
        className="dr2-offline__brand"
        viewBox={`${WORDMARK_VIEW.x} ${WORDMARK_VIEW.y} ${WORDMARK_VIEW.w} ${WORDMARK_VIEW.h}`}
        aria-hidden="true"
        focusable="false"
      >
        {WORDMARK_PATHS.map((path) => (path.stroke
          ? <path key={path.d} d={path.d} fill="none" stroke="currentColor" strokeWidth={path.stroke} />
          : <path key={path.d} d={path.d} fill="currentColor" fillRule={path.rule} stroke="currentColor" strokeWidth={WORDMARK_OUTLINE} strokeLinejoin="round" />))}
      </svg>
      <form className="dr2-offline__composer" onSubmit={submit}>
        <label className="dr2-offline__sr" htmlFor="dr2-question">Your question</label>
        <textarea
          id="dr2-question"
          ref={boxRef}
          className="dr2-offline__input"
          rows={1}
          value={question}
          disabled={hidden}
          placeholder="Ask about a company, a filing or a number"
          onChange={(event) => { setQuestion(event.target.value); setTried(false); fit(); }}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) submit(event);
          }}
        />
        <button type="submit" className="dr2-offline__send" aria-label="Send question" disabled={hidden || !filled}>
          <ArrowUp size={18} strokeWidth={2.25} aria-hidden="true" />
        </button>
      </form>
      <p className="dr2-offline__line" role="status">
        {tried ? 'Not sent. ' : ''}The research workspace is not connected in this build yet.
      </p>
    </div>
  );
}

/* A report link (#/DeepResearch?c=…&r=…) opens the report viewer, which reads
   c/r from its own query string. Its "Dashboard" button posts {type:'indago-menu'}
   (the chat frame posts OPEN_INDAGO_NAVIGATION); both open the menu, and only from
   this frame on this origin. "Back to chat" goes back in history when the entry
   before the report is the Deep Research chat, else follows its href to the chat. */
function ReportViewer({ src, chatIdx = null }) {
  const frameRef = useRef(null);
  useEffect(() => {
    const openNavigation = (event) => {
      const frame = frameRef.current;
      if (!frame?.contentWindow || event.source !== frame.contentWindow || event.origin !== window.location.origin) return;
      const type = event.data?.type;
      if (type === 'indago-menu' || type === OPEN_INDAGO_NAVIGATION) openIndagoNavigation(frame);
    };
    window.addEventListener('message', openNavigation);
    return () => window.removeEventListener('message', openNavigation);
  }, []);
  return (
    <>
      <nav className="dr2-report__bar" aria-label="Callisto report">
        <a
          className="dr2-workspace__retry dr2-report__back"
          href={`#${DR_ROUTE}`}
          onClick={(event) => {
            if (drBackAction(drHistoryIdx(), chatIdx) !== 'back') return;
            event.preventDefault();
            window.history.back();
          }}
        >← Back to Callisto chat</a>
      </nav>
      <div className="dr2-workspace__content">
        <iframe
          ref={frameRef}
          className="dr2-workspace__frame is-ready"
          src={src}
          data-indago-surface="dr-report"
          data-indago-auth-frame="research"
          title="Callisto report"
          allow="clipboard-read; clipboard-write; fullscreen"
        />
      </div>
    </>
  );
}

/* Deep Research (the LibreChat embed). Query's "Deep-dive in Deep Research →"
   question is read here at the top level (so a Retry remount keeps it) and
   consumed once the page has mounted (so a reload or a later visit never
   re-applies it); a ?thread=… link opens that chat in the frame, a report link
   (?c=…&r=…) opens the report viewer, and a new link while the page is open
   remounts the frame on it. */
export default function DeepResearch() {
  return DEEP_RESEARCH_ENABLED ? <DeepResearchWorkspace /> : <DeepResearchUnavailable />;
}

/* INDAGO_DEEP_RESEARCH=off (a beta without it): a static notice, no status calls, no frame. */
function DeepResearchUnavailable() {
  return (
    <div className="flex min-h-[60vh] items-center justify-center p-8">
      <div className="max-w-md text-center">
        <h1 className="text-lg font-medium text-white/80">Callisto</h1>
        <p className="mt-2 text-sm text-white/55">Callisto is not available in this build.</p>
        <a href="#/Home" className="mt-4 inline-block text-sm text-black/70 underline underline-offset-4">Back to Home</a>
      </div>
    </div>
  );
}

function DeepResearchWorkspace() {
  const location = useLocation();
  const [attempt, setAttempt] = useState(0);
  // automatic tries from the error screen (bounded); a click on "Try again" is not counted
  const [autoUsed, setAutoUsed] = useState(0);
  const autoRetry = useCallback(() => { setAutoUsed((value) => value + 1); setAttempt((value) => value + 1); }, []);
  const [handoff] = useState(() => createBrowserStorage('sessionStorage'));
  const [prompt, setPrompt] = useState(() => readDrPrefill(handoff));
  useEffect(() => { clearDrPrefill(handoff); }, [handoff]);
  useEffect(() => installPriceHistoryBridge(window), []);   // the price card's range buttons
  const target = parseDrTarget(location.search);
  const reportShown = isDrReportTarget(target);
  // after a report, "Back to Deep Research chat" opens a plain new chat, not the old question again
  useEffect(() => { if (reportShown) setPrompt(''); }, [reportShown]);
  // the history entry of the chat shown last in this mount, so the report's Back can return to it
  const chatIdxRef = useRef(null);
  useEffect(() => { if (!reportShown) chatIdxRef.current = drHistoryIdx(); }, [reportShown, location.key]);
  // Owner rule (2026-10-12): the workspace always opens with Deep Research OFF; the
  // composer's Deep Research button runs it. No lane parameter on the frame URL.
  const src = buildDrFrameSrc({ target, prompt });
  const prefill = drPrefillByMessage({ target, prompt });
  // the chat the frame shows now ('' = a new chat); the address carries it for a reload
  const [thread, setThread] = useState(() => target?.thread || '');
  // the memory tab waits until the opening screen has gone (it must never sit on top of it)
  const [splashUp, setSplashUp] = useState(true);
  return (
    <section className="dr2-workspace" aria-label="Callisto">
      <DrReadyNotifier />
      <div hidden={splashUp && !reportShown} data-testid="dr2-memory-host">
        <DeepResearchMemoryDrawer />
      </div>
      {isDrReportTarget(target) ? (
        <ReportViewer key={drTargetKey(target)} src={buildDrReportSrc(target)} chatIdx={chatIdxRef.current} />
      ) : (
        <Workspace
          key={`${attempt}|${drTargetKey(target)}`}
          src={src}
          prefill={prefill}
          onPrefillTaken={() => setPrompt('')}
          onRetry={() => setAttempt(value => value + 1)}
          onAutoRetry={autoUsed < MAX_AUTO_REMOUNTS ? autoRetry : null}
          onThread={setThread}
          onSplashChange={setSplashUp}
        />
      )}
      {/* Overlay slot above the workspace (pointer-events pass through until a child
          takes them). dr2:memory-drawer — the memory drawer mounts here with ONE line:
          <DrMemoryDrawer thread={thread} />   (thread: the chat shown now; '' = new chat) */}
      <div className="dr2-workspace__drawer-slot" data-testid="dr2-drawer-slot" data-thread={thread || undefined}>
      </div>
    </section>
  );
}

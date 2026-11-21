// Deep Research opening screen: honest progress and a time estimate.
//
// Progress comes from real signals, never a fake timer alone: the session check,
// the embedded app's own resource loads (compared with how many the last
// successful open needed), and the document finishing. The estimate is the
// median of this browser's last five opens (default 8 s before the first one).
// Pure functions only, so they are unit-tested without a DOM.

export const OPEN_PROFILE_KEY = 'indago-dr2-open-profile';
export const DEFAULT_ESTIMATE_MS = 8_000;
export const DEFAULT_RESOURCES = 45;
const KEEP = 5;
const MAX_MS = 120_000;

export const LOADER_STEPS = [
  'Checking your session',
  'Loading the workspace',
  'Starting Callisto',
];

export function readOpenProfile(storage) {
  try {
    const raw = JSON.parse(storage?.getItem(OPEN_PROFILE_KEY) || 'null');
    const ms = Array.isArray(raw?.ms)
      ? raw.ms.filter((v) => Number.isFinite(v) && v > 0 && v < MAX_MS).slice(-KEEP)
      : [];
    const resources = Number.isFinite(raw?.resources) && raw.resources > 0 ? Math.round(raw.resources) : 0;
    return { ms, resources };
  } catch {
    return { ms: [], resources: 0 };
  }
}

export function recordOpen(storage, profile, ms, resources) {
  if (!Number.isFinite(ms) || ms <= 0 || ms >= MAX_MS) return profile;
  const next = {
    ms: [...profile.ms, Math.round(ms)].slice(-KEEP),
    resources: resources > 0 ? Math.round(resources) : profile.resources,
  };
  try {
    storage?.setItem(OPEN_PROFILE_KEY, JSON.stringify(next));
  } catch { /* storage blocked: the estimate simply stays at its default */ }
  return next;
}

export function estimateMs(profile) {
  const list = [...(profile?.ms ?? [])].sort((a, b) => a - b);
  if (list.length === 0) return DEFAULT_ESTIMATE_MS;
  const mid = Math.floor(list.length / 2);
  const median = list.length % 2 ? list[mid] : (list[mid - 1] + list[mid]) / 2;
  return Math.max(1_500, Math.round(median));
}

/** What the embedded app has loaded so far (same-origin frame; safe on failure). */
export function frameSignals(frame) {
  try {
    const win = frame?.contentWindow;
    const doc = frame?.contentDocument;
    if (!win || !doc || win.location.href === 'about:blank') {
      return { resources: 0, failed: 0, complete: false };
    }
    const entries = win.performance?.getEntriesByType?.('resource') ?? [];
    let failed = 0;
    for (const entry of entries) {
      const code = entry.responseStatus;
      if (typeof code === 'number' && code >= 500 && /\/xyz\/assets\//.test(entry.name)) failed += 1;
    }
    return { resources: entries.length, failed, complete: doc.readyState === 'complete' };
  } catch {
    return { resources: 0, failed: 0, complete: false };
  }
}

/**
 * phase: 'checking' | 'opening' | 'ready'; elapsed/estimate in ms; signals from
 * frameSignals; expected = resources the last good open needed (0 = unknown).
 * Returns { percent (0-100), step (0-3), eta (text), slow (boolean) }.
 */
export function loaderView({ phase, elapsed, estimate, signals, expected, retrying = false, warmup = false }) {
  if (phase === 'ready') return { percent: 100, step: 3, eta: 'Ready', slow: false };
  const time = Math.min(0.95, Math.max(0, elapsed / Math.max(estimate, 1)));
  let percent;
  let step;
  if (phase === 'checking') {
    step = 0;
    percent = 12 * Math.min(1, elapsed / 1_500);
  } else {
    const want = expected > 0 ? expected : DEFAULT_RESOURCES;
    const loaded = Math.min(0.97, (signals?.resources ?? 0) / want);
    // loading: resources against the last good open, never ahead of the clock by much
    const loading = 12 + 58 * Math.max(Math.min(loaded, time + 0.25), time * 0.9);
    if (!signals?.complete) {
      step = 1;
      percent = loading;
    } else {
      // the page is in; the app is starting: the clock drives the rest
      step = 2;
      percent = Math.max(loading, 70 + 28 * time);
    }
  }
  percent = Math.max(0, Math.min(98, Math.round(percent)));
  const remaining = estimate - elapsed;
  const slow = elapsed > estimate * 1.25 + 3_000;
  let eta;
  if (retrying) eta = warmup ? 'Callisto is starting up after an update — retrying…' : 'The connection hiccuped — retrying…';
  else if (warmup) eta = WARMUP_MESSAGE;
  else if (slow && step === 2) eta = BUSY_STARTING_MESSAGE;
  else if (slow) eta = 'Taking longer than usual. The Callisto server may be busy — still working…';
  else if (remaining > 1_500) eta = `About ${Math.ceil(remaining / 1_000)} s left`;
  else eta = 'Almost there…';
  return { percent, step, eta, slow };
}

/** The opening screen's one status line: the active step and the time left, or the
 *  loader's own message alone when it says more (after an update, a retry, a slow server). */
export function loaderStatus(view) {
  if (!view || !(view.step < LOADER_STEPS.length)) return 'Ready';
  const step = LOADER_STEPS[Math.max(0, view.step)];
  const eta = typeof view.eta === 'string' ? view.eta : '';
  if (!eta) return step;
  return /^About \d+ s left$|^Almost there/.test(eta) ? `${step} · ${eta}` : eta;
}

// ── Startup after an update (DROPEN 2026-10-10) ─────────────────────────────
// Right after the Callisto server restarts, the embedded app needs about a minute
// before its composer appears. /api/xyz/status reports the server's age
// (uptime_s); inside this window the screen says so plainly, waits longer before
// calling the open "stuck", and does not record the open as this browser's usual.
export const WARMUP_WINDOW_S = 300;
export const WARMUP_ESTIMATE_MS = 60_000;
export const WARMUP_MESSAGE = 'Callisto is starting up after an update — about 1 minute.';
export const BUSY_STARTING_MESSAGE = 'The server is busy, so Callisto is starting slowly. It retries by itself — no need to do anything.';
// The page is in but the composer has not appeared for this long: reload the frame
// (a request the app waits on may have been lost while the server was busy).
export const STARTING_STALL_MS = 45_000;
export const STARTING_STALL_WARMUP_MS = 90_000;
// When every retry is spent, the error screen tries again by itself (no dead end).
export const AUTO_REMOUNT_MS = 15_000;
export const MAX_AUTO_REMOUNTS = 2;

/** true when the server started recently enough to call this a startup. */
export function isWarmup(uptimeS) {
  return typeof uptimeS === 'number' && Number.isFinite(uptimeS) && uptimeS >= 0 && uptimeS < WARMUP_WINDOW_S;
}

/** true when the document is in but the composer has not appeared for too long.
 *  attempt = frame reloads so far: each one doubles the wait (45 -> 90 -> 180 s, never
 *  past HARD_CAP_MS), so a boot that is only slow on a busy server still gets to open. */
export function startingStalled(startingSince, now, { warmup = false, attempt = 0 } = {}) {
  if (typeof startingSince !== 'number' || !Number.isFinite(startingSince)) return false;
  const base = warmup ? STARTING_STALL_WARMUP_MS : STARTING_STALL_MS;
  const n = Number.isInteger(attempt) && attempt > 0 ? Math.min(attempt, 8) : 0;
  return now - startingSince >= Math.min(HARD_CAP_MS, base * 2 ** n);
}

/** Seconds left before the error screen tries again by itself, or null when it will not. */
export function autoRemountLeft({ errorAt, now, remountsUsed, sessionError = false }) {
  if (sessionError || !Number.isFinite(errorAt) || !(remountsUsed < MAX_AUTO_REMOUNTS)) return null;
  return Math.max(0, Math.ceil((errorAt + AUTO_REMOUNT_MS - now) / 1_000));
}

// ── Retry policy (night1 RELIABILITY) ───────────────────────────────────────
// A busy core answers late or with a JSON 503 instead of the app. That is not a
// reason to show "Unable to open": retry with backoff first, and judge "stuck"
// by the time since the last real progress, not the time since mount.
export const RETRY_BACKOFF_MS = Object.freeze([2_000, 5_000, 10_000]);
export const STALL_MS = 60_000;          // no new resource / readiness change for this long
export const HARD_CAP_MS = 180_000;      // absolute ceiling per attempt, even while trickling

/** Backoff before retry number `attempt` (0-based), or null when retries are spent. */
export function retryDelay(attempt) {
  return Number.isInteger(attempt) && attempt >= 0 && attempt < RETRY_BACKOFF_MS.length
    ? RETRY_BACKOFF_MS[attempt] : null;
}

/** /api/xyz/status outcome → 'ok' | 'session' (never retried) | 'offline' (never retried) | 'retry'.
 *  'offline': this build has no workspace service at all: the route answers 404, a 200 whose
 *  body is not JSON (a dev server's HTML shell for an unknown path), or the request failed
 *  outright (failed: a network error, not our own timeout). A real service that is busy or
 *  starting (JSON ready:false, 502/503/504, a timeout) is retried as before. */
export function classifyStatus({ status = 0, ready = false, aborted = false, json = true, failed = false } = {}) {
  if (status === 401 || status === 403) return 'session';
  if (status === 404) return 'offline';
  if (status === 200 && json === false && !aborted) return 'offline';
  if (status === 0 && failed === true && !aborted) return 'offline';
  if (status === 200 && ready === true && !aborted) return 'ok';
  return 'retry';            // timeout, 5xx, starting, not ready
}

/** inspectWorkspaceFrame result → 'ready' | 'session' | 'retry' | 'wait'. A JSON
 *  503 frame document reads 'unavailable': the core was busy, so reload it. */
export function classifyFrame(result) {
  if (result === 'ready') return 'ready';
  if (result === 'auth-error') return 'session';
  if (result === 'unavailable') return 'retry';
  return 'wait';
}

/** Track the last moment the frame made progress (more resources, or document complete). */
export function trackProgress(prev, signals, now) {
  const resources = signals?.resources ?? 0;
  const complete = Boolean(signals?.complete);
  if (!prev) return { resources, complete, at: now, since: now };
  if (resources > prev.resources || (complete && !prev.complete)) {
    return { resources, complete, at: now, since: prev.since };
  }
  return { ...prev, resources: Math.max(prev.resources, resources), complete: prev.complete || complete };
}

/** true when this attempt should be treated as stuck (then: retry, or show the error). */
export function isStalled(progress, now, { stallMs = STALL_MS, capMs = HARD_CAP_MS } = {}) {
  if (!progress) return false;
  return now - progress.at >= stallMs || now - progress.since >= capMs;
}

// After a frame reload the OLD document (e.g. the JSON 503) stays in the frame until
// the new response commits. Classifying it again would spend every retry while one
// slow reload is still pending; wait for a new document (bounded by STALL_MS).
export function markReload(frameDocument, now) {
  return frameDocument ? { doc: frameDocument, at: now } : null;
}

export function awaitingReload(pending, frameDocument, now, { maxMs = STALL_MS } = {}) {
  if (!pending || !pending.doc) return false;
  return frameDocument === pending.doc && now - pending.at < maxMs;
}

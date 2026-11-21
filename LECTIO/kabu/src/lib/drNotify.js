// "Research ready" notifications for Deep Research.
//
// Pure helpers behind components/DrReadyNotifier.jsx: they read the run listing the
// core already serves (GET /api/research/library: the signed-in person's OWN research,
// each with its newest run's status) and decide when a run finished that this page saw
// start or run, what to say, and how often to look. No network or DOM here.

export const LIBRARY_API = '/api/research/library?limit=20';
export const LIVE_STATUSES = Object.freeze(['queued', 'running']);
export const READY_STATUSES = Object.freeze(['published', 'partial']);
const STOPPED_STATUSES = Object.freeze(['error']);

/** Poll spacing (ms). Never below 15 s; the idle look is slower still. */
export const POLL_LIVE_MS = 15_000;
export const POLL_IDLE_MS = 45_000;
export const POLL_MAX_BACKOFF_MS = 300_000;
/** A hidden tab with nothing live looks this many more times (a run may still be registering), then stops. */
export const HIDDEN_GRACE_POLLS = 3;

export const NOTIFY_KEY = 'indago-dr-notify';
const ASK_AGAIN_AFTER_MS = 14 * 24 * 3600 * 1000;
const TITLE_MAX = 90;

const isLive = (status) => LIVE_STATUSES.includes(status);

/** { id, status, title, thread } for a listing row with a run, else null. */
export function runOf(item) {
  const run = item && typeof item === 'object' ? item.lastRun : null;
  if (!run || typeof run.id !== 'string' || typeof run.status !== 'string') return null;
  const titles = [item.lastResult?.title, item.title, run.prompt];
  const title = titles.find((value) => typeof value === 'string' && value.trim()) || 'Callisto';
  return {
    id: run.id, status: run.status,
    title: title.trim().replace(/\s+/g, ' ').slice(0, TITLE_MAX),
    thread: typeof item.thread === 'string' ? item.thread : '',
  };
}

export function newTracker() {
  return { baseline: null, live: {}, done: [] };
}

/**
 * Fold one listing into the tracker.
 * `started`: runs that went live after the first look (these may ask for permission).
 * `finished`: runs this page saw live (or that appeared whole after the first look) and that now ended.
 * `anyLive`: something is still queued or running.
 */
export function observe(tracker, items) {
  const rows = (Array.isArray(items) ? items : []).map(runOf).filter(Boolean);
  const first = tracker.baseline === null;
  const baseline = { ...(tracker.baseline || {}) };
  const live = { ...tracker.live };
  const done = new Set(tracker.done);
  const started = [];
  const finished = [];
  const present = new Set(rows.map((row) => row.id));
  for (const row of rows) {
    if (isLive(row.status)) {
      if (!(row.id in live)) {
        live[row.id] = row.title;
        if (!first) started.push(row);
      }
      done.delete(row.id); // a resumed run can finish again
    } else {
      const wasSeen = row.id in live;
      const appearedWhole = !first && !(row.id in baseline);
      if ((wasSeen || appearedWhole) && !done.has(row.id)) {
        finished.push(row);
        done.add(row.id);
      }
      delete live[row.id];
    }
    baseline[row.id] = row.status;
  }
  for (const id of Object.keys(live)) if (!present.has(id)) delete live[id]; // deleted while running
  return {
    tracker: { baseline, live, done: [...done].slice(-200) },
    started, finished, anyLive: Object.keys(live).length > 0,
  };
}

/** Milliseconds until the next look, or null to stop looking until the page wakes. */
export function nextDelay({ anyLive, hidden, hiddenIdle = 0, failures = 0 }, intervals = {}) {
  const liveMs = Math.max(POLL_LIVE_MS, intervals.live ?? POLL_LIVE_MS);
  const idleMs = Math.max(POLL_LIVE_MS, intervals.idle ?? POLL_IDLE_MS);
  let base;
  if (anyLive) base = liveMs;
  else if (!hidden) base = idleMs;
  else if (hiddenIdle < HIDDEN_GRACE_POLLS) base = liveMs;
  else return null;
  return Math.min(POLL_MAX_BACKOFF_MS, base * 2 ** Math.min(failures, 5));
}

/** What to tell the person about a finished run, or null when nothing should be said. */
export function messageFor(run) {
  if (READY_STATUSES.includes(run.status)) return { title: `Research ready: ${run.title}`, kind: 'ready' };
  if (STOPPED_STATUSES.includes(run.status)) return { title: `Research stopped: ${run.title}`, kind: 'stopped' };
  return null; // cancelled: the person did that
}

/** "(2) Deep Research" while results wait; the app's own title is kept under it. */
export function badgeTitle(base, count) {
  const clean = withoutBadge(base);
  return count > 0 ? `(${count}) ${clean}` : clean;
}
export function withoutBadge(title) {
  return String(title ?? '').replace(/^\(\d+\)\s/, '');
}

/** Ask for notification permission only when it is still undecided and not recently declined. */
export function shouldAsk({ supported, permission, stored, now = Date.now() }) {
  if (!supported || permission !== 'default') return false;
  const declinedAt = Number(stored?.declinedAt);
  return !(Number.isFinite(declinedAt) && now - declinedAt < ASK_AGAIN_AFTER_MS);
}

export function readStored(storage) {
  try {
    const value = JSON.parse(storage?.getItem(NOTIFY_KEY) || 'null');
    return value && typeof value === 'object' ? value : {};
  } catch { return {}; }
}
export function writeDeclined(storage, now = Date.now()) {
  try { storage?.setItem(NOTIFY_KEY, JSON.stringify({ declinedAt: now })); } catch { /* storage blocked: asked again next time */ }
}

const THREAD_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
/** Where a clicked notification goes: the chat the run lives in, else the Deep Research home. */
export function targetHash(thread) {
  return THREAD_RE.test(thread || '') ? `#/DeepResearch?thread=${thread.toLowerCase()}` : '#/DeepResearch';
}

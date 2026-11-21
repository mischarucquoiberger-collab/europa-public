/* Deep Research URL contract (one product, one route).
 *
 * Host route:  #/DeepResearch            — the LibreChat embed titled "Deep Research".
 * Aliases:     #/DeepResearch2, #/XYZ    — redirect here, keeping their query string.
 * Host query (all optional, validated here, never trusted raw):
 *   thread=<uuid>        a LibreChat conversation  → frame /xyz/c/<uuid>
 *   c=<id>&r=<id>        a research conversation/result (store.viewer_url, report
 *                        "supersedes" links, thread-less panel rows)
 *                        → the report viewer DR_REPORT_VIEWER?c=<c>&r=<r> (it opens
 *                        the report from its own query string). The chat frame has
 *                        no handler for these ids yet; sending them there landed the
 *                        reader on an empty new chat. buildDrFrameSrc keeps the
 *                        /xyz/c/new?indago_c=&indago_r= form for that future handler.
 * Query → Deep Research handoff: Query.jsx parks the question in sessionStorage
 * under DR_PREFILL_KEY; the host claims it ONCE. A question whose encoded query
 * string fits DR_PROMPT_QS_MAX opens /xyz/c/new?prompt=<text> (LibreChat's
 * useQueryParams fills the composer and strips it). A longer one (Japanese is 9
 * bytes a character once %-encoded) would push the request head past the 16 KiB
 * h11 / Node limit and the frame would get a 400, so it is NEVER put in the URL:
 * the frame opens /xyz/c/new and the host hands the text over by a same-origin
 * postMessage when the frame's composer reports ready (DR_PREFILL_READY →
 * DR_PREFILL_TEXT → DR_PREFILL_TAKEN). Neither path adds a submit flag or
 * submits, so the Confirm Deep Research card still gates spend.
 *
 * Frame side (owned by the DR lane): read indago_c/indago_r once on load, open
 * the target in the thread, and on failure show an inline message. It must never
 * fall back to window.top navigation to #/DeepResearch (that is this page).
 */

export const DR_ROUTE = '/DeepResearch';
export const DR_ALIAS_ROUTES = Object.freeze(['/DeepResearch2', '/XYZ']);
export const DR_PREFILL_KEY = 'indago-dr-prefill';
export const DR_FRAME_BASE = '/xyz/c/';
export const DR_PROMPT_MAX = 6000;
/** Longest `prompt=…` query string (encoded bytes) put in the frame URL; longer text goes by message. */
export const DR_PROMPT_QS_MAX = 4000;
/** Frame → host: the composer is mounted and listening. */
export const DR_PREFILL_READY = 'indago:dr-prefill-ready';
/** Host → frame: { type, text } — fill the composer (never submit). */
export const DR_PREFILL_TEXT = 'indago:dr-prefill';
/** Frame → host: the text was applied; the host drops it (no re-apply on reload or retry). */
export const DR_PREFILL_TAKEN = 'indago:dr-prefill-taken';
/** The still-served report viewer; it reads ?c=&r= itself (same id pattern as ID_RE). */
export const DR_REPORT_VIEWER = '/static/deepresearch-app/index.html';

const THREAD_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const ID_RE = /^[A-Za-z0-9_.:-]{1,80}$/;

function params(search) {
  const raw = typeof search === 'string' ? search : '';
  try { return new URLSearchParams(raw.startsWith('?') ? raw.slice(1) : raw); } catch { return new URLSearchParams(); }
}

/** Validated deep-link target from the host route's query string, or null. */
export function parseDrTarget(search) {
  const query = params(search);
  const thread = (query.get('thread') || '').trim();
  if (THREAD_RE.test(thread)) return { thread: thread.toLowerCase(), conversationId: '', resultId: '' };
  const conversationId = (query.get('c') || '').trim();
  if (!ID_RE.test(conversationId)) return null;
  const resultId = (query.get('r') || '').trim();
  return { thread: '', conversationId, resultId: ID_RE.test(resultId) ? resultId : '' };
}

/** Stable identity of a target; the host remounts its frame when it changes. */
export function drTargetKey(target) {
  if (!target) return '';
  return target.thread ? `t:${target.thread}` : `c:${target.conversationId}|${target.resultId}`;
}

/** True when the target is a research report (c/r) rather than a chat thread. */
export function isDrReportTarget(target) {
  return Boolean(target && !target.thread && target.conversationId);
}

/** The report viewer src for a c/r target, or '' for anything else. */
export function buildDrReportSrc(target) {
  if (!isDrReportTarget(target)) return '';
  const query = new URLSearchParams({ c: target.conversationId });
  if (target.resultId) query.set('r', target.resultId);
  return `${DR_REPORT_VIEWER}?${query.toString()}`;
}

function handoffText(target, prompt) {
  if (target?.thread || target?.conversationId) return '';   // a deep link never takes the Query question
  return typeof prompt === 'string' ? prompt.trim().slice(0, DR_PROMPT_MAX) : '';
}

function promptQuery(text) {
  return text ? new URLSearchParams({ prompt: text }).toString() : '';
}

/** True when the handed-off question fits the frame URL (encoded length, not characters). */
export function drPromptFitsUrl(text) {
  const qs = promptQuery(typeof text === 'string' ? text : '');
  return qs.length > 0 && qs.length <= DR_PROMPT_QS_MAX;
}

/** The handed-off question the host must deliver by postMessage ('' when none, or when it rides in ?prompt=). */
export function drPrefillByMessage({ target = null, prompt = '' } = {}) {
  const text = handoffText(target, prompt);
  return text && !drPromptFitsUrl(text) ? text : '';
}

/** The iframe src for a target and/or a handed-off prompt (always short: see DR_PROMPT_QS_MAX). */
export function buildDrFrameSrc({ target = null, prompt = '' } = {}) {
  if (target?.thread) return `${DR_FRAME_BASE}${target.thread}`;
  const query = new URLSearchParams();
  const text = handoffText(target, prompt);
  if (target?.conversationId) {
    query.set('indago_c', target.conversationId);
    if (target.resultId) query.set('indago_r', target.resultId);
  } else if (drPromptFitsUrl(text)) {
    query.set('prompt', text);
  }
  const qs = query.toString();
  return `${DR_FRAME_BASE}new${qs ? `?${qs}` : ''}`;
}

/** The prefill message type from this frame on this origin, or '' for anything else. */
export function drFrameMessageType(event, frameWindow, origin) {
  if (!event || !frameWindow || event.source !== frameWindow || event.origin !== origin) return '';
  const type = event.data?.type;
  return type === DR_PREFILL_READY || type === DR_PREFILL_TAKEN ? type : '';
}

/**
 * What the host does with a frame message while `pending` text waits:
 * { send } — post `send` back to the frame (same origin only); { taken: true } — drop the text; null — ignore.
 */
export function drPrefillAction(event, frameWindow, origin, pending) {
  const text = typeof pending === 'string' ? pending : '';
  if (!text) return null;
  const type = drFrameMessageType(event, frameWindow, origin);
  if (type === DR_PREFILL_READY) return { send: { type: DR_PREFILL_TEXT, text } };
  if (type === DR_PREFILL_TAKEN) return { taken: true };
  return null;
}

function currentStore(store) {
  try {
    return store && !(typeof store.isCurrent === 'function' && !store.isCurrent()) ? store : null;
  } catch {
    return null;
  }
}

/** The Query handoff question, without consuming it (safe to call during render). */
export function readDrPrefill(store) {
  const current = currentStore(store);
  if (!current) return '';
  try {
    const value = current.getItem(DR_PREFILL_KEY);
    return typeof value === 'string' ? value.trim().slice(0, DR_PROMPT_MAX) : '';
  } catch {
    return '';
  }
}

/** Consume the handoff question so it applies to one visit only (call after commit). */
export function clearDrPrefill(store) {
  const current = currentStore(store);
  if (!current) return;
  try { current.removeItem(DR_PREFILL_KEY); } catch { /* blocked storage: nothing was parked */ }
}

/** Read and REMOVE the handoff question in one step. */
export function claimDrPrefill(store) {
  const value = readDrPrefill(store);
  clearDrPrefill(store);
  return value;
}

/** The report viewer's "Back to Deep Research chat": 'back' (history.back()) when the entry just before the
    report is the Deep Research chat (HashRouter's history.state.idx is exactly one past the chat's), else
    'navigate' (follow the #/DeepResearch href: a report opened from a link, a new tab or a reload). */
export function drBackAction(currentIdx, chatIdx) {
  return Number.isInteger(currentIdx) && Number.isInteger(chatIdx) && currentIdx === chatIdx + 1 ? 'back' : 'navigate';
}

/** HashRouter's index of the current history entry, or null when unknown. */
export function drHistoryIdx() {
  try {
    const idx = window.history.state?.idx;
    return Number.isInteger(idx) ? idx : null;
  } catch {
    return null;
  }
}

/** Where an alias route lands: the DR route with the same query string. */
export function drAliasTarget(search) {
  const raw = typeof search === 'string' ? search : '';
  return { pathname: DR_ROUTE, search: raw && raw !== '?' ? (raw.startsWith('?') ? raw : `?${raw}`) : '' };
}

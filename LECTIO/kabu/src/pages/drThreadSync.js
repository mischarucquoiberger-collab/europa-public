// Deep Research reload restore (s12 dr-ux): the outer address follows the chat the
// embedded workspace shows, so a reload (or Back from another page) reopens the
// CURRENT research instead of a blank new chat.
//
// The frame is same-origin; its LibreChat router moves between /xyz/c/new and
// /xyz/c/<uuid> without telling the host. The host reads the frame's pathname
// (cheap, no messages, no LibreChat change) and rewrites ONLY the `thread` query
// parameter of #/DeepResearch with history.replaceState: no new history entry, no
// hashchange/popstate, so the router does not remount the frame. A reload then
// parses ?thread=<uuid> (drRoutes.parseDrTarget) and opens /xyz/c/<uuid>.
// Pure functions only, so they are unit-tested without a DOM.

import { DR_ROUTE } from '../lib/drRoutes.js';

const UUID = '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}';
const CHAT_PATH_RE = new RegExp(`^/xyz/c/(new|${UUID})/?$`, 'i');

/**
 * The chat a frame pathname shows: a lowercase uuid, '' for a new chat (/xyz/c/new),
 * or null for anything that is not a chat page (login, agents, search, about:blank):
 * null means "leave the address alone".
 */
export function frameThread(pathname) {
  if (typeof pathname !== 'string') return null;
  const match = CHAT_PATH_RE.exec(pathname);
  if (!match) return null;
  return match[1].toLowerCase() === 'new' ? '' : match[1].toLowerCase();
}

/**
 * The outer hash with its `thread` parameter set to `thread` ('' removes it), or null
 * when nothing should change: the hash is not the Deep Research route (the reader
 * already left), it is a report link (?c=…), or it already says this thread.
 */
export function syncedHash(hash, thread) {
  if (typeof hash !== 'string' || thread == null) return null;
  const raw = hash.startsWith('#') ? hash.slice(1) : hash;
  const queryAt = raw.indexOf('?');
  const path = queryAt === -1 ? raw : raw.slice(0, queryAt);
  if (path !== DR_ROUTE) return null;
  let query;
  try { query = new URLSearchParams(queryAt === -1 ? '' : raw.slice(queryAt + 1)); } catch { return null; }
  // a report target owns this address; the chat frame is not mounted there
  if (query.get('c')) return null;
  const current = (query.get('thread') || '').toLowerCase();
  if (current === thread) return null;
  if (thread) query.set('thread', thread);
  else query.delete('thread');
  const qs = query.toString();
  return `#${DR_ROUTE}${qs ? `?${qs}` : ''}`;
}

/**
 * Read the frame, rewrite the address when the chat changed. Returns the thread the
 * frame shows (or null when unknown). `win` is the host window (injected for tests).
 */
export function syncThreadToAddress(frame, win = globalThis.window) {
  let pathname = null;
  try {
    pathname = frame?.contentWindow?.location?.pathname ?? null;
  } catch {
    return null;            // cross-origin error document: nothing to read
  }
  const thread = frameThread(pathname);
  if (thread == null || !win?.location || !win?.history) return thread;
  const next = syncedHash(win.location.hash, thread);
  if (next) {
    try {
      // keep the router's own history state (idx/key) so Back and drHistoryIdx still work
      win.history.replaceState(win.history.state, '', `${win.location.pathname}${win.location.search}${next}`);
    } catch { /* a sandboxed or detached window: the reload simply opens a new chat */ }
  }
  return thread;
}

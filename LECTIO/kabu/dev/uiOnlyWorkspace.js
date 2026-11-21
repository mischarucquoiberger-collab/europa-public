/* UI-only Deep Research workspace.

   public/xyz holds the built workspace client (the screen Deep Research opens after its splash).
   That client expects a research service behind it; this build has none. This Vite plugin stands
   in for it on the local dev / preview server: it serves the client's page for its own routes and
   answers the client's start-up requests from the fixed data below, so the real screen renders.
   Nothing is stored here; a question typed into the screen goes to the Callisto research desk bridge
   when vite.config.js proxies the chat to it and it is up, otherwise it gets the "not connected"
   answer below, never a made-up one. */
import fs from 'node:fs';
import path from 'node:path';

export const WORKSPACE_BASE = '/xyz';
export const NOT_CONNECTED = "Callisto's answer service is not connected in this build yet.";

const EPOCH = '2026-01-01T00:00:00.000Z';
const GUEST = Object.freeze({
  id: 'ui-guest', _id: 'ui-guest', username: 'guest', email: 'guest@example.com', name: 'Guest', avatar: '',
  role: 'USER', provider: 'local', plugins: [], emailVerified: true, termsAccepted: true,
  createdAt: EPOCH, updatedAt: EPOCH,
});
const STARTUP = Object.freeze({
  appTitle: 'Callisto', socialLogins: [], discordLoginEnabled: false, facebookLoginEnabled: false,
  githubLoginEnabled: false, googleLoginEnabled: false, appleLoginEnabled: false, openidLoginEnabled: false,
  samlLoginEnabled: false, openidLabel: '', openidImageUrl: '', openidAutoRedirect: false, samlLabel: '',
  samlImageUrl: '', serverDomain: '', emailLoginEnabled: true, registrationEnabled: false,
  socialLoginEnabled: false, emailEnabled: false, passwordResetEnabled: false, checkBalance: false,
  showBirthdayIcon: false, helpAndFaqURL: '/', sharedLinksEnabled: false, publicSharedLinksEnabled: false,
  instanceProjectId: 'instance', sharePointFilePickerEnabled: false, version: 'ui-only',
  customFooter: '',          // no footer line
  interface: {
    endpointsMenu: true, modelSelect: true, parameters: true, sidePanel: true, presets: true, multiConvo: false,
    bookmarks: true, memories: false, prompts: true, agents: false, temporaryChat: true, runCode: false,
    webSearch: false, fileSearch: false, fileCitations: false, peoplePicker: {}, marketplace: { use: false },
  },
});
// the workspace's own lane names (constants in its code): the endpoint and its two models
const ENDPOINT = 'Indago';
const MODELS = Object.freeze(['indago-query', 'indago-deep-research']);
const ENDPOINT_LABEL = 'Callisto';
// what a signed-in member may use: the side rail's prompts and bookmarks, and a temporary chat
const PERMISSIONS = Object.freeze({
  PROMPTS: { USE: true, CREATE: true, SHARED_GLOBAL: false },
  BOOKMARKS: { USE: true },
  TEMPORARY_CHAT: { USE: true },
  MULTI_CONVO: { USE: false },
  AGENTS: { USE: false, CREATE: false, SHARED_GLOBAL: false },
  MEMORIES: { USE: false, CREATE: false, UPDATE: false, READ: false, OPT_OUT: false },
  RUN_CODE: { USE: false },
  WEB_SEARCH: { USE: false },
});

const json = (body, status = 200) => ({ status, type: 'application/json; charset=utf-8', body: JSON.stringify(body) });

/** The answer to one workspace request. `pathname` is the path after the /xyz base. */
export function workspaceAnswer(method, pathname) {
  const verb = String(method || 'GET').toUpperCase();
  if (pathname === '/health') return { status: 200, type: 'text/plain; charset=utf-8', body: 'OK' };
  if (pathname === '/api/auth/refresh') return json({ token: 'ui-only', user: GUEST });
  if (pathname === '/api/auth/logout') return json({ message: 'ok' });
  if (pathname === '/api/user') return json(GUEST);
  if (pathname === '/api/config') return json(STARTUP);
  if (pathname === '/api/endpoints') {
    return json({ [ENDPOINT]: { type: 'custom', userProvide: false, userProvideURL: false, modelDisplayLabel: ENDPOINT_LABEL, order: 0 } });
  }
  if (pathname === '/api/endpoints/token-config') return json({});
  if (pathname === '/api/models') return json({ [ENDPOINT]: [...MODELS] });
  if (pathname.startsWith('/api/roles')) return json({ name: 'USER', permissions: PERMISSIONS });
  if (verb !== 'GET') {
    // sending a question, saving a setting, uploading a file: there is no service to take it
    if (/^\/api\/(agents|ask|edit|messages|convos|files|research|projects)\b/.test(pathname)) {
      return json({ message: NOT_CONNECTED, error: NOT_CONNECTED }, 503);
    }
    return json({});
  }
  if (pathname.startsWith('/api/convos')) return json({ conversations: [], nextCursor: null });
  if (pathname.startsWith('/api/projects')) return json({ projects: [], nextCursor: null });
  if (pathname.startsWith('/api/user/settings')) return json([]);
  if (pathname === '/api/user/terms') return json({ termsAccepted: true });
  if (['/api/presets', '/api/files', '/api/tags', '/api/categories', '/api/plugins', '/api/schedules'].includes(pathname)) return json([]);
  if (pathname === '/api/search/enable') return json(false);
  if (pathname === '/api/banner') return json(null);
  if (pathname.startsWith('/api/keys')) return json({ expiresAt: null });
  if (pathname.startsWith('/api/agents/chat/active')) return json({ activeJobIds: [] });
  if (pathname.startsWith('/api/agents')) return json({ object: 'list', data: [], first_id: '', last_id: '', has_more: false });
  if (pathname.startsWith('/api/messages')) return json([]);
  return json({});
}

/** The answer to a request the workspace makes to the host app's own /api, or null when the
 *  request is not one of them (the rest of /api stays as it is: there is no backend). */
export function hostAnswer(method, pathname) {
  const verb = String(method || 'GET').toUpperCase();
  if (pathname.startsWith('/api/memory/')) return json({ detail: 'Not Found' }, 404);   // no memory feature here
  if (!pathname.startsWith('/api/research/')) return null;
  if (verb !== 'GET') return json({ detail: NOT_CONNECTED, message: NOT_CONNECTED }, 503);
  if (pathname === '/api/research/library') return json({ items: [] });
  if (pathname === '/api/research/conversations') return json({ conversations: [] });
  if (pathname === '/api/research/dr2/settings') return json({});
  return json({ detail: 'Not Found' }, 404);
}

function send(res, answer) {
  res.statusCode = answer.status;
  res.setHeader('Content-Type', answer.type);
  res.setHeader('Cache-Control', 'no-store');
  res.end(answer.body);
}

/* The Callisto research desk bridge (LECTIO/callisto backend/workspace_bridge.py), when vite.config.js
   proxies the chat to it: a sent question and its answer stream go there while it is up; when it is
   down or not configured the "not connected" answer above stays. */
export const BRIDGE_BASE = `${WORKSPACE_BASE}/api/agents/chat`;

/** Whether a request belongs to the bridge: the question, its answer stream, a stop (not the job list),
 *  and the reads that follow an answer (its conversation, messages and title, the chat list). */
export function isBridgeRequest(pathname, method = 'GET') {
  if (pathname.startsWith(`${BRIDGE_BASE}/`)) return !pathname.startsWith(`${BRIDGE_BASE}/active`);
  if (String(method).toUpperCase() !== 'GET') return false;
  return pathname === `${WORKSPACE_BASE}/api/convos` || pathname.startsWith(`${WORKSPACE_BASE}/api/convos/`)
    || pathname.startsWith(`${WORKSPACE_BASE}/api/messages/`);
}

/** The bridge's address from Vite's proxy table, or null when the chat is not proxied. */
export function bridgeTarget(proxy) {
  const entry = proxy && proxy[BRIDGE_BASE];
  const target = typeof entry === 'string' ? entry : entry && entry.target;
  return typeof target === 'string' && target ? target : null;
}

/** A cached health check of the bridge (true while `GET <origin>/api/health` answers 200). */
export function bridgeProbe(origin, { ttlMs = 3000, timeoutMs = 800, fetchImpl = globalThis.fetch } = {}) {
  let at = 0;
  let up = false;
  return async () => {
    if (Date.now() - at < ttlMs) return up;
    try {
      const answer = await fetchImpl(new URL('/api/health', origin), { signal: AbortSignal.timeout(timeoutMs) });
      up = answer.ok;
    } catch { up = false; }
    at = Date.now();
    return up;
  };
}

/** Connect-style middleware. `clientDir` is the folder that holds the built workspace client;
 *  `bridgeUp` (optional) says whether the research desk bridge answers the chat. */
export function workspaceMiddleware(clientDir, { bridgeUp } = {}) {
  return (req, res, next) => {
    let pathname;
    try { pathname = new URL(req.url, 'http://local').pathname; } catch { return next(); }
    if (bridgeUp && isBridgeRequest(pathname, req.method)) {
      const rest = pathname.slice(WORKSPACE_BASE.length);
      bridgeUp().then((up) => (up ? next() : send(res, workspaceAnswer(req.method, rest))), () => send(res, workspaceAnswer(req.method, rest)));
      return undefined;
    }
    // the page's own readiness check before it mounts the workspace
    if (pathname === '/api/xyz/status') return send(res, json({ ready: true }));
    // what the workspace asks the host app for (its research list, its options, memory)
    const host = hostAnswer(req.method, pathname);
    if (host) return send(res, host);
    if (pathname !== WORKSPACE_BASE && !pathname.startsWith(`${WORKSPACE_BASE}/`)) return next();
    const rest = pathname.slice(WORKSPACE_BASE.length) || '/';
    if (rest === '/health' || rest.startsWith('/api/')) return send(res, workspaceAnswer(req.method, rest));
    // a real file of the client: the static file server takes it
    const file = path.join(clientDir, rest);
    if (rest !== '/' && file.startsWith(clientDir) && fs.existsSync(file) && fs.statSync(file).isFile()) return next();
    // anything else under the base is one of the client's own routes (c/new, …): its page
    return send(res, { status: 200, type: 'text/html; charset=utf-8', body: fs.readFileSync(path.join(clientDir, 'index.html')) });
  };
}

function withBridge(proxy) {
  const target = bridgeTarget(proxy);
  return target ? { bridgeUp: bridgeProbe(target) } : {};
}

export default function uiOnlyWorkspace() {
  return {
    name: 'ui-only-workspace',
    configureServer(server) {
      server.middlewares.use(workspaceMiddleware(path.join(server.config.root, 'public', 'xyz'), withBridge(server.config.server.proxy)));
    },
    configurePreviewServer(server) {
      server.middlewares.use(workspaceMiddleware(path.resolve(server.config.root, server.config.build.outDir, 'xyz'), withBridge(server.config.preview?.proxy ?? server.config.server.proxy)));
    },
  };
}

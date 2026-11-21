// Route chunks, fetched when the menu opens or a menu row / company row is
// pointed at or focused, so the click lands on a module that is already in
// memory instead of the black loading screen while a chunk downloads.
// pages.config.js registers the SAME importers it lazy-loads (Vite shares one
// chunk per module); this module itself imports no page, so anything that
// imports it stays light. Code only: no page renders, no API is called.

const IMPORTERS = {};

/** pages.config.js: route ("/Reports") -> () => import(...) for prefetchable routes. */
export function registerRouteImporters(map) {
  for (const [route, importer] of Object.entries(map || {})) {
    if (typeof importer === 'function') IMPORTERS[route] = importer;
  }
}

const started = new Map();

function constrained(nav = globalThis.navigator) {
  const connection = nav && /** @type {any} */ (nav).connection;
  return !!(connection && (connection.saveData || /(^|-)2g$/.test(String(connection.effectiveType || ''))));
}

/** Starts loading one route's chunk (once); returns the promise or null. */
export function prefetchRoute(route, { importers = IMPORTERS, nav = globalThis.navigator } = {}) {
  try {
    const key = String(route || '').split('?')[0];
    const importer = importers[key];
    if (!importer || constrained(nav)) return null;
    if (!started.has(key)) {
      started.set(key, Promise.resolve().then(importer).catch(() => { started.delete(key); }));
    }
    return started.get(key);
  } catch {
    return null;
  }
}

/** Every menu route, one after another on idle time (the menu just opened). */
export function prefetchMenuRoutes(routes, { win = globalThis.window, importers = IMPORTERS } = {}) {
  const queue = (routes || Object.keys(importers)).filter((route) => importers[String(route).split('?')[0]]);
  if (!win || constrained(win.navigator) || !queue.length) return () => {};
  let cancelled = false;
  let handle = 0;
  const idle = typeof win.requestIdleCallback === 'function'
    ? (fn) => win.requestIdleCallback(fn, { timeout: 1500 })
    : (fn) => win.setTimeout(fn, 200);
  const cancelIdle = typeof win.cancelIdleCallback === 'function'
    ? (h) => win.cancelIdleCallback(h) : (h) => win.clearTimeout(h);
  const step = () => {
    if (cancelled || !queue.length) return;
    const pending = prefetchRoute(queue.shift(), { importers, nav: win.navigator });
    Promise.resolve(pending).finally(() => { if (!cancelled) handle = idle(step); });
  };
  handle = idle(step);
  return () => { cancelled = true; cancelIdle(handle); };
}

export const __test = { started };

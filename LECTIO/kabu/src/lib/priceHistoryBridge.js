/* The host fetch bridge the workspace's price card asks for (window.parent.__indagoResearchFetch, read by
   the workspace frame tagged data-indago-auth-frame="research"). With it, the card's range buttons
   (1D 5D 1M 6M YTD 1Y 5Y) read GET /api/price-history/{ticker}, which the Callisto research desk answers
   from Massive bars. Reads go out exactly as the frame's own same-origin read would; anything that
   writes is refused, as it is without a bridge. No token is lent: this build has no sign-in. */

export function researchFetch(_source, input, init = {}) {
  const method = String(init.method ?? 'GET').toUpperCase();
  let url;
  try { url = new URL(String(input), window.location.origin); } catch { url = null; }
  if (!url || url.origin !== window.location.origin || (method !== 'GET' && method !== 'HEAD')) {
    const refused = new Error('Research request is outside this build.');
    refused.name = 'ResearchBridgeUnavailable';
    return Promise.reject(refused);
  }
  return fetch(url.pathname + url.search, { ...init, method, credentials: 'same-origin' });
}

/** Installs the bridge on `win` unless one is there already; returns the matching clean-up. */
export function installPriceHistoryBridge(win) {
  if (!win || typeof win.__indagoResearchFetch === 'function') return () => {};
  win.__indagoResearchFetch = researchFetch;
  return () => { if (win.__indagoResearchFetch === researchFetch) delete win.__indagoResearchFetch; };
}

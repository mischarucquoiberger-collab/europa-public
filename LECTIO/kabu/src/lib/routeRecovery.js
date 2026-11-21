// Retry only failed chunk transport, never arbitrary component/module errors.
// A persistent old-build URL requires an explicit reload, not a reload loop
// that can destroy a research draft or obscure an active server-side run.
const preloadFailures = new WeakSet();

export function observePreloadFailure(event) {
  const error = event?.payload;
  if (error && typeof error === 'object') preloadFailures.add(error);
  // Do not preventDefault: Vite must reject the import for the route boundary.
}

export function isChunkFailure(error) {
  return !!error && (preloadFailures.has(error) ||
    /Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module|Unable to preload CSS|Loading chunk .* failed/i.test(String(error.message || '')));
}

export async function loadRoute(importer, wait = ms => new Promise(resolve => setTimeout(resolve, ms))) {
  try {
    return await importer();
  } catch (error) {
    if (!isChunkFailure(error)) throw error;
    await wait(300);
    return await importer(); // one retry, then a visible, user-controlled recovery
  }
}

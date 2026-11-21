// One guarded facade over this browser's storage. Storage can be blocked
// (private mode, a sandboxed frame, an enterprise policy): reads then answer
// null and writes throw, so every caller keeps its own in-memory fallback.
function rawStorage(kind) {
  try { return globalThis[kind] || null; } catch { return null; }
}

/** @param {"localStorage" | "sessionStorage"} [kind] */
export function createBrowserStorage(kind = "localStorage") {
  const store = () => rawStorage(kind);
  return {
    get length() { return store()?.length ?? 0; },
    key(index) { return store()?.key(index) ?? null; },
    getItem(key) { return store()?.getItem(key) ?? null; },
    setItem(key, value) {
      const target = store();
      if (!target) throw new Error("Browser storage is not available");
      target.setItem(key, value);
    },
    removeItem(key) {
      const target = store();
      if (!target) throw new Error("Browser storage is not available");
      target.removeItem(key);
    },
    /** The key a storage event names: null when the whole store was cleared. */
    eventKey(key) { return key === null ? null : typeof key === "string" ? key : undefined; },
  };
}

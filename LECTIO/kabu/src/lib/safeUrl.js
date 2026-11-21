const FALLBACK_ORIGIN = "http://localhost";

function currentOrigin() {
  return typeof window !== "undefined" && window.location?.origin
    ? window.location.origin
    : FALLBACK_ORIGIN;
}

/** Return an absolute external URL only when it uses plain HTTP(S). */
export function safeExternalUrl(value) {
  if (typeof value !== "string" || !value.trim()) return null;
  try {
    const parsed = new URL(value.trim());
    if (!['http:', 'https:'].includes(parsed.protocol)) return null;
    if (parsed.username || parsed.password) return null;
    return parsed.href;
  } catch {
    return null;
  }
}

/**
 * Convert a same-origin URL to a credential-free relative path. This helper is
 * intentionally origin-only; callers still have to validate the endpoint and
 * identifiers they place in that path.
 */
export function safeSameOriginPath(value, origin = currentOrigin()) {
  if (typeof value !== "string" || !value.trim()) return null;
  try {
    const parsed = new URL(value.trim(), origin);
    if (parsed.origin !== origin || parsed.username || parsed.password) return null;
    parsed.searchParams.delete("t");
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return null;
  }
}

function containsNavigationBoundary(value) {
  for (const character of value) {
    const code = character.charCodeAt(0);
    if (character === '\\' || code <= 0x20 || code === 0x7f) return true;
  }
  return false;
}

/** Model-provided app links must stay app-relative through URL/router parsing. */
export function safeAppNavigation(value, origin = currentOrigin()) {
  if (typeof value !== "string" || !value.startsWith("/") || value.startsWith("//")
      || containsNavigationBoundary(value)) return null;
  const path = safeSameOriginPath(value, origin);
  if (!path) return null;
  try {
    const encodedPath = path.split(/[?#]/, 1)[0];
    // Do not accept nested encodings of a separator that a later decoder
    // could reinterpret. Query values are not navigation path separators.
    if (/%25/i.test(encodedPath)) return null;
    const decodedPath = decodeURIComponent(encodedPath);
    if (decodedPath.startsWith("//") || containsNavigationBoundary(decodedPath)) return null;
    return path;
  } catch {
    return null;
  }
}

export function normalizeReportFileName(value, extension = null) {
  if (typeof value !== "string") return null;
  const name = value.trim();
  if (!/^report_[0-9A-Za-z.]+_[0-9a-f]{8}\.(?:html|pdf)$/.test(name)) return null;
  if (extension && !name.endsWith(`.${extension}`)) return null;
  return name;
}

export function reportDownloadPath(fileName, { inline = false } = {}) {
  const file = normalizeReportFileName(fileName);
  if (!file) return null;
  const params = new URLSearchParams();
  if (inline) params.set("inline", "1");
  params.set("file", file);
  return `/download?${params}`;
}

/** Accept only the report download endpoint and its two documented params. */
export function safeReportUrl(value, origin = currentOrigin()) {
  const relative = safeSameOriginPath(value, origin);
  if (!relative) return null;
  try {
    const parsed = new URL(relative, origin);
    if (parsed.pathname !== "/download" || parsed.hash) return null;
    let hasUnexpectedParam = false;
    parsed.searchParams.forEach((_value, key) => {
      if (key !== "file" && key !== "inline") hasUnexpectedParam = true;
    });
    if (hasUnexpectedParam) return null;
    if (parsed.searchParams.getAll("file").length !== 1) return null;
    if (parsed.searchParams.getAll("inline").length > 1) return null;
    const file = normalizeReportFileName(parsed.searchParams.get("file"));
    if (!file) return null;
    const inline = parsed.searchParams.get("inline");
    if (inline !== null && inline !== "1") return null;
    return reportDownloadPath(file, { inline: inline === "1" });
  } catch {
    return null;
  }
}

export function extractReportFileName(value, origin = currentOrigin()) {
  const safe = safeReportUrl(value, origin);
  if (!safe) return null;
  return new URL(safe, origin).searchParams.get("file");
}

// One share link for a finished report, used by the ready screen's Share and the
// viewer's Copy link: the #/Viewer page for that report (never the raw
// /download file), copied to the clipboard with the same toast.
import { normalizeJobId } from "./reportStorage.js";
import { safeReportUrl } from "./safeUrl.js";

/**
 * The app path of the viewer for a report ("/Viewer?url=…&title=…&jobId=…"), or null.
 * @param {{ url?: string | null, title?: string | null, jobId?: string | null }} report
 * @param {string} [origin]
 */
export function reportViewerPath(report, origin) {
  const { url, title, jobId } = report || {};
  const safe = safeReportUrl(url, origin);
  if (!safe) return null;
  const params = new URLSearchParams({ url: safe });
  const name = String(title || "").trim();
  if (name) params.set("title", name);
  const id = normalizeJobId(jobId);
  if (id) params.set("jobId", id);
  return `/Viewer?${params}`;
}

/** The absolute link to that viewer page (hash routing), or null. */
export function reportShareLink(report, loc = typeof window !== "undefined" ? window.location : null) {
  if (!loc) return null;
  const path = reportViewerPath(report, loc.origin);
  return path ? `${loc.origin}${loc.pathname}#${path}` : null;
}

export const SHARE_TOAST = { title: "Link copied", description: "It opens this report in the viewer. Your notes stay on this device." };
export const SHARE_FAILED_TOAST = { title: "Copy failed", description: "Your browser blocked clipboard access." };

/** Copies the report's share link and reports the result through `notify` (a toast function). */
export function copyReportShareLink(report, notify, clipboard = typeof navigator !== "undefined" ? navigator.clipboard : null) {
  const link = reportShareLink(report);
  if (!link) {
    notify({ title: "Nothing to share", description: "This report has no viewer link yet." });
    return Promise.resolve(false);
  }
  if (!clipboard?.writeText) {
    notify(SHARE_FAILED_TOAST);
    return Promise.resolve(false);
  }
  return clipboard.writeText(link).then(
    () => { notify(SHARE_TOAST); return true; },
    () => { notify(SHARE_FAILED_TOAST); return false; },
  );
}

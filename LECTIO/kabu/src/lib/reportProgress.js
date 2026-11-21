// Presentation only: never infer work completed or activity from elapsed time.
const UNCERTAIN_STAGES = new Set(["Starting", "Company Info", "Data Fetch", "Extraction"]);
export const STATUS_FRESH_MS = 15_000;

export function reportProgress(status, { receivedAt = 0, now = Date.now(), hasError = false } = {}) {
  const progress = typeof status?.progress === "number" && Number.isFinite(status.progress)
    ? Math.min(100, Math.max(0, status.progress)) : 0;
  const message = typeof status?.message === "string" ? status.message.trim() : "";
  const fallback = status?.status === "queued"
    ? "Queued — waiting for a report worker."
    : "Waiting for the next report status update…";
  const fresh = receivedAt > 0 && now >= receivedAt && now - receivedAt <= STATUS_FRESH_MS;
  const estimate = status?.eta_seconds;
  // Filing discovery has no known remaining-document count. Its cold-cache
  // duration can exceed historical estimates by minutes. Do not countdown it.
  // Later estimates come directly from each server poll (including increases),
  // not a second client-side timer that can only decrease toward a false zero.
  const etaSeconds = status?.status === "running" && !UNCERTAIN_STAGES.has(status?.step)
    && fresh && !hasError && typeof estimate === "number" && Number.isFinite(estimate) && estimate > 0
    ? Math.min(600, Math.round(estimate)) : null;
  const count = status?.edinet_count;
  const filingsFound = Number.isInteger(count) && count > 0 ? count : null;
  return { progress, message: message || fallback, etaSeconds, filingsFound };
}

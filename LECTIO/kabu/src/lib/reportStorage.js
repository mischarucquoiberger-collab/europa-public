import {
  extractReportFileName,
  normalizeReportFileName,
  reportDownloadPath,
  safeExternalUrl,
  safeReportUrl,
} from "./safeUrl.js";
import { createBrowserStorage } from "./browserStorage.js";

export const REPORT_HISTORY_PREFIX = "kabu.report.history.v2.";
export const ACTIVE_REPORT_PREFIX = "kabu.report.active.v2.";
const LEGACY_HISTORY_KEY = "reports_history";
const LEGACY_ACTIVE_JOBS_KEY = "active_generating_jobs";
const LEGACY_ACTIVE_JOB_KEY = "active_generating";
const MAX_HISTORY = 50;
const JOB_ID_RE = /^[0-9a-f]{32}$/;

export function normalizeJobId(value) {
  if (typeof value !== "string") return null;
  const normalized = value.trim().toLowerCase();
  return JOB_ID_RE.test(normalized) ? normalized : null;
}

export function createReportStorage() {
const browserStorage = createBrowserStorage();
function storage() { return browserStorage; }

function parseJSON(value) {
  try { return JSON.parse(value); } catch { return null; }
}

function historyKey(jobId) {
  const id = normalizeJobId(jobId);
  return id ? `${REPORT_HISTORY_PREFIX}${id}` : null;
}

function activeKey(jobId) {
  const id = normalizeJobId(jobId);
  return id ? `${ACTIVE_REPORT_PREFIX}${id}` : null;
}

function normalizeSource(source) {
  if (!source || typeof source !== "object") return null;
  return {
    ...source,
    id: typeof source.id === "string" || typeof source.id === "number" ? source.id : undefined,
    type: String(source.type || "web").slice(0, 40),
    title: String(source.title || "").slice(0, 500),
    url: safeExternalUrl(source.url),
    snippet: String(source.snippet || "").slice(0, 1_200),
    date: String(source.date || "").slice(0, 80),
  };
}

function normalizeReportEntry(value) {
  if (!value || typeof value !== "object") return null;
  const jobId = normalizeJobId(value.jobId || value.job_id);
  if (!jobId) return null;
  const htmlFile = normalizeReportFileName(
    value.html_file || extractReportFileName(value.html),
    "html",
  );
  const pdfFile = normalizeReportFileName(
    value.pdf_file || extractReportFileName(value.pdf),
    "pdf",
  );
  const html = safeReportUrl(value.html) || (htmlFile ? reportDownloadPath(htmlFile) : null);
  const pdf = safeReportUrl(value.pdf) || (pdfFile ? reportDownloadPath(pdfFile) : null);
  if (!html && !pdf) return null;
  return {
    ...value,
    jobId,
    ticker: String(value.ticker || value.stock_code || "").trim().slice(0, 12),
    companyName: String(value.companyName || value.company_name || "").trim().slice(0, 240),
    html,
    pdf,
    html_file: htmlFile,
    pdf_file: pdfFile,
    sources: Array.isArray(value.sources)
      ? value.sources.slice(0, 160).map(normalizeSource).filter(Boolean)
      : [],
  };
}

function normalizeActiveEntry(value) {
  if (!value || typeof value !== "object") return null;
  const jobId = normalizeJobId(value.jobId || value.job_id);
  if (!jobId) return null;
  return {
    ...value,
    jobId,
    ticker: String(value.ticker || value.stock_code || "").trim().slice(0, 12),
    companyName: String(value.companyName || value.company_name || "").trim().slice(0, 240),
  };
}

function migrateArrayKey(legacyKey, normalize, write) {
  const store = storage();
  if (!store) return;
  const raw = store.getItem(legacyKey);
  if (!raw) return;
  const parsed = parseJSON(raw);
  const values = Array.isArray(parsed) ? parsed : [parsed];
  let successful = true;
  for (const value of values) {
    const normalized = normalize(value);
    if (!normalized) continue;
    successful = write(normalized) && successful;
  }
  if (successful) store.removeItem(legacyKey);
}

function readPrefix(prefix, normalize) {
  const store = storage();
  if (!store) return [];
  const values = [];
  const keys = [];
  for (let index = 0; index < store.length; index += 1) {
    const key = store.key(index);
    if (key?.startsWith(prefix)) keys.push(key);
  }
  for (const key of keys) {
    const value = normalize(parseJSON(store.getItem(key)));
    if (value) values.push(value);
    else store.removeItem(key);
  }
  return values;
}

function upsertReportHistory(value) {
  const store = storage();
  const entry = normalizeReportEntry(value);
  const key = entry && historyKey(entry.jobId);
  if (!store || !entry || !key) return false;
  try {
    const previous = normalizeReportEntry(parseJSON(store.getItem(key)));
    store.setItem(key, JSON.stringify(previous ? { ...previous, ...entry } : entry));
    return true;
  } catch {
    return false;
  }
}

function migrateReportHistory() {
  migrateArrayKey(LEGACY_HISTORY_KEY, normalizeReportEntry, upsertReportHistory);
}

function readReportHistory() {
  migrateReportHistory();
  const entries = readPrefix(REPORT_HISTORY_PREFIX, normalizeReportEntry)
    .sort((a, b) => {
      const right = new Date(b.finishedAt || 0).getTime();
      const left = new Date(a.finishedAt || 0).getTime();
      return (Number.isFinite(right) ? right : 0) - (Number.isFinite(left) ? left : 0);
    });
  const store = storage();
  for (const stale of entries.slice(MAX_HISTORY)) {
    try { store?.removeItem(historyKey(stale.jobId)); } catch { /* Best-effort history cleanup must not discard the new entry. */ }
  }
  return entries.slice(0, MAX_HISTORY);
}

function findReportHistory(jobId) {
  const key = historyKey(jobId);
  const store = storage();
  if (!key || !store) return null;
  migrateReportHistory();
  return normalizeReportEntry(parseJSON(store.getItem(key)));
}

function removeReportHistory(jobId) {
  const key = historyKey(jobId);
  if (!key) return false;
  try { storage()?.removeItem(key); return true; } catch { return false; }
}

function upsertActiveReport(value) {
  const store = storage();
  const entry = normalizeActiveEntry(value);
  const key = entry && activeKey(entry.jobId);
  if (!store || !entry || !key) return false;
  try {
    const previous = normalizeActiveEntry(parseJSON(store.getItem(key)));
    store.setItem(key, JSON.stringify(previous ? { ...previous, ...entry } : entry));
    return true;
  } catch {
    return false;
  }
}

function migrateActiveReports() {
  migrateArrayKey(LEGACY_ACTIVE_JOBS_KEY, normalizeActiveEntry, upsertActiveReport);
  migrateArrayKey(LEGACY_ACTIVE_JOB_KEY, normalizeActiveEntry, upsertActiveReport);
}

function readActiveReports() {
  migrateActiveReports();
  return readPrefix(ACTIVE_REPORT_PREFIX, normalizeActiveEntry);
}

function removeActiveReport(jobId) {
  const key = activeKey(jobId);
  if (!key) return false;
  try { storage()?.removeItem(key); return true; } catch { return false; }
}

function isReportStorageKey(rawKey) {
  const key = browserStorage.eventKey(rawKey);
  if (key === undefined) return false;
  return key === null
    || key === LEGACY_HISTORY_KEY
    || key === LEGACY_ACTIVE_JOBS_KEY
    || key === LEGACY_ACTIVE_JOB_KEY
    || key?.startsWith(REPORT_HISTORY_PREFIX)
    || key?.startsWith(ACTIVE_REPORT_PREFIX);
}
return { normalizeReportEntry, upsertReportHistory, readReportHistory,
  findReportHistory, removeReportHistory, upsertActiveReport, readActiveReports,
  removeActiveReport, isReportStorageKey };
}

/**
 * A GET /api/reports/mine row as a Recent entry, or null. The server sends the
 * account's own finished reports with a source count only; the row's Sources
 * button loads the list through /status when it is opened.
 */
export function serverReportEntry(row) {
  if (!row || typeof row !== "object") return null;
  const entry = createReportStorage().normalizeReportEntry({
    jobId: row.job_id,
    ticker: row.ticker,
    companyName: row.company_name,
    html_file: row.html_file,
    pdf_file: row.pdf_file,
    finishedAt: row.finished_at || row.created_at || null,
    status: row.status === "warning" ? "warning" : "complete",
  });
  if (!entry) return null;
  const count = Number(row.source_count);
  return { ...entry, sourceCount: Number.isInteger(count) && count > 0 ? count : 0, fromServer: true };
}

/**
 * This browser's history plus the account's server rows, one row per jobId,
 * newest first. A local row wins (it already holds the sources and any
 * warning text); server rows fill in what this browser has never seen.
 */
export function mergeReportHistory(local, serverRows, limit = MAX_HISTORY) {
  const seen = new Set();
  const merged = [];
  for (const entry of Array.isArray(local) ? local : []) {
    if (!entry?.jobId || seen.has(entry.jobId)) continue;
    seen.add(entry.jobId);
    merged.push(entry);
  }
  for (const row of Array.isArray(serverRows) ? serverRows : []) {
    const entry = serverReportEntry(row);
    if (!entry || seen.has(entry.jobId)) continue;
    seen.add(entry.jobId);
    merged.push(entry);
  }
  const time = (entry) => {
    const value = new Date(entry.finishedAt || 0).getTime();
    return Number.isFinite(value) ? value : 0;
  };
  return merged
    .map((entry, index) => [time(entry), index, entry])
    .sort((a, b) => b[0] - a[0] || a[1] - b[1])
    .slice(0, limit)
    .map((item) => item[2]);
}

// Synchronous consumers can use these conveniences. Async components capture
// createReportStorage() once so late completions retain their original scope.
export const normalizeReportEntry = (...args) => createReportStorage().normalizeReportEntry(...args);
export const upsertReportHistory = (...args) => createReportStorage().upsertReportHistory(...args);
export const readReportHistory = () => createReportStorage().readReportHistory();
export const findReportHistory = (...args) => createReportStorage().findReportHistory(...args);
export const removeReportHistory = (...args) => createReportStorage().removeReportHistory(...args);
export const upsertActiveReport = (...args) => createReportStorage().upsertActiveReport(...args);
export const readActiveReports = () => createReportStorage().readActiveReports();
export const removeActiveReport = (...args) => createReportStorage().removeActiveReport(...args);
export const isReportStorageKey = (...args) => createReportStorage().isReportStorageKey(...args);

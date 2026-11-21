import React, { useEffect, useState, useCallback, useMemo, useRef } from "react";
import { Download, Trash2, BookOpen, ArrowUpRight, Search } from "lucide-react";
import SearchBar from "@/components/home/SearchBar";
import { useCircleTransition } from "@/components/CircleTransition";
import { deleteJob, getStatus, buildBareDownloadUrl } from "@/api/backend";
import { safeSameOriginPath } from "@/lib/safeUrl";
import SourcesModal from "@/components/report/SourcesModal";
import { MorphFilters, MorphItem, adaptiveStagger } from "@/components/MorphReveal";
import { toast } from "@/components/ui/use-toast";
import { createReportStorage, mergeReportHistory } from "@/lib/reportStorage";
import { displayCompanyName } from "@/lib/companyIndex";

// Known-symbol English name overrides for large US companies. Kept in sync with
// the same table in GenerateReport.jsx so every page renders the company name
// in Latin characters even if a stored value in localStorage or on the server
// is in another script.
const KNOWN_EN_NAMES = {
  "AAPL": "Apple Inc.",
  "MSFT": "Microsoft Corporation",
  "NVDA": "NVIDIA Corporation",
  "AMZN": "Amazon.com, Inc.",
  "GOOGL": "Alphabet Inc.",
  "META": "Meta Platforms, Inc.",
  "TSLA": "Tesla, Inc.",
  "BRK.B": "Berkshire Hathaway Inc.",
  "JPM": "JPMorgan Chase & Co.",
};
const CJK_RE = /[\u3000-\u303F\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF\uFF00-\uFFEF]/;
// Shown in the same display case as the search dropdown (displayCompanyName).
const toLatinName = (name, ticker) => {
  const t = ticker ? String(ticker).trim() : "";
  if (!name) return KNOWN_EN_NAMES[t] || t;
  const str = String(name);
  if (!CJK_RE.test(str)) return displayCompanyName(str);
  if (KNOWN_EN_NAMES[t]) return KNOWN_EN_NAMES[t];
  const cleaned = str
    .replace(/[\u3000-\u303F\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF\uFF00-\uFFEF]/g, "")
    .replace(/\s+/g, " ")
    .trim();
  return cleaned ? displayCompanyName(cleaned) : t;
};

// The account's finished reports as the server keeps them (GET /api/reports/mine),
// so Recent is the same on a new browser or device. Any failure is silent: Recent
// then shows this browser's own history, as before.
/** @param {{ signal?: AbortSignal }} [options] */
export async function fetchMyReports({ signal } = {}) {
  const res = await fetch("/api/reports/mine", { signal });
  if (!res.ok) return [];
  const data = await res.json().catch(() => null);
  return Array.isArray(data?.reports) ? data.reports : [];
}

// Strip anything that isn't a valid ticker character. Takes the first
// whitespace/comma-separated token so a legacy free-form entry like
// "aapl, apple" collapses to "aapl" instead of "aaplapple".
const sanitizeTicker = (raw) => {
  const s = String(raw || "").trim();
  if (!s) return "";
  const first = s.split(/[\s,]+/)[0] || s;
  return first.replace(/[^0-9A-Za-z.]/g, "").slice(0, 10);
};

// Recent shows one row per company: the newest run, plus how many runs exist.
// `rows` is newest-first (mergeReportHistory), so the first row seen for a
// ticker is its newest. Display-only — nothing is hidden from storage, and
// deleting the shown run lets the next-newest one surface on the next render.
// Rows without a ticker are never merged with each other.
export function groupRecentByTicker(rows, limit = 12) {
  const groups = [];
  const byTicker = new Map();
  for (const row of Array.isArray(rows) ? rows : []) {
    if (!row?.jobId) continue;
    const key = String(row.ticker || "").trim().toUpperCase();
    const group = key ? byTicker.get(key) : null;
    if (group) {
      group.runs += 1;
      continue;
    }
    const next = { item: row, runs: 1 };
    if (key) byTicker.set(key, next);
    groups.push(next);
  }
  return groups.slice(0, limit);
}

// Recent rows are saved once, when a job finishes. A row saved as "warning"
// keeps that label even after the backend's /status reports the job as
// "complete" (e.g. a report whose only issue was withheld unverified claims).
// On each page load, re-check the newest such rows through the same status
// API, a few at a time, once per job. Only a "complete" answer clears the
// row's warning; any other status, a 404/401 or a network error leaves the
// row exactly as it is.
const RESYNC_MAX_ROWS = 20;
const RESYNC_MAX_IN_FLIGHT = 3;
const resyncedStatus = new Map(); // jobId -> Promise<status | null>, per page load

export function resyncWarningHistory(rows, { fetchStatus, findEntry, saveEntry, onChange,
  isCancelled = () => false, seen = resyncedStatus }) {
  const pending = (Array.isArray(rows) ? rows : [])
    .filter((row) => row?.status === "warning" && row.jobId)
    .slice(0, RESYNC_MAX_ROWS);
  let next = 0;
  const worker = async () => {
    while (!isCancelled() && next < pending.length) {
      const { jobId } = pending[next++];
      if (!seen.has(jobId)) {
        seen.set(jobId, Promise.resolve()
          .then(() => fetchStatus(jobId))
          .then((st) => st?.status ?? null, () => null));
      }
      const status = await seen.get(jobId);
      if (isCancelled() || status !== "complete") continue;
      const current = findEntry(jobId);
      if (current?.status !== "warning") continue;
      if (saveEntry({ ...current, status: "complete", warning: null })) onChange?.();
    }
  };
  return Promise.all(Array.from({ length: Math.min(RESYNC_MAX_IN_FLIGHT, pending.length) }, worker));
}

export default function Home() {
  const [{ findReportHistory, isReportStorageKey, readActiveReports, readReportHistory, removeActiveReport,
    removeReportHistory, upsertActiveReport, upsertReportHistory }] = useState(createReportStorage);
  const [history, setHistory] = useState(() => readReportHistory());
  // Server rows (this account, any device), merged with local history by jobId.
  const [serverRows, setServerRows] = useState([]);
  // The empty state waits for that list (or a short grace period), so a new
  // device does not flash "generate your first report" above its own reports.
  const [serverListSettled, setServerListSettled] = useState(false);
  const recentRows = useMemo(() => mergeReportHistory(history, serverRows), [history, serverRows]);
  const recentGroups = useMemo(() => groupRecentByTicker(recentRows, 12), [recentRows]);
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [activeSources, setActiveSources] = useState([]);
  const [activeCompany, setActiveCompany] = useState("");
  const [hoveredItem, setHoveredItem] = useState(null);
  // Delete is irreversible (purges state + localStorage + backend job), so the
  // trash control arms a two-step inline confirm instead of deleting on the
  // first tap. `confirmDeleteId` holds the jobId currently awaiting confirmation;
  // it auto-disarms after a few seconds so a stray click can't leave it primed.
  const [confirmDeleteId, setConfirmDeleteId] = useState(null);
  const confirmDeleteTimerRef = useRef(null);
  // Tracks the report whose Sources modal is currently open, so a slow getStatus
  // resolve for a previously-clicked report can't overwrite the modal contents
  // after a different report's Sources button has been opened.
  const activeSourcesJob = useRef(null);
  // On touch devices there is no hover, so the per-row action buttons (which are
  // hover-revealed on desktop) must be permanently visible — otherwise they are
  // unreachable. Detect a coarse pointer once.
  const coarsePointer = useMemo(
    () => typeof window !== "undefined" && window.matchMedia && window.matchMedia("(hover: none)").matches,
    []
  );
  // Array of in-progress jobs so multiple reports can run concurrently.
  const [generating, setGenerating] = useState([]);
  const { navigateWithReveal } = useCircleTransition();

  useEffect(() => {
    const refresh = (event) => {
      if (event && !isReportStorageKey(event.key)) return;
      setHistory(readReportHistory());
    };
    window.addEventListener("storage", refresh);
    return () => window.removeEventListener("storage", refresh);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const grace = setTimeout(() => setServerListSettled(true), 1500);
    fetchMyReports({ signal: controller.signal })
      .then((rows) => { if (!controller.signal.aborted) setServerRows(rows); })
      .catch(() => { /* Recent falls back to this browser's history. */ })
      .finally(() => { if (!controller.signal.aborted) setServerListSettled(true); });
    return () => { clearTimeout(grace); controller.abort(); };
  }, []);

  // Re-check Recent rows still labelled "warning" (see resyncWarningHistory).
  // Runs after the first render and never blocks it; stops on unmount.
  useEffect(() => {
    let cancelled = false;
    resyncWarningHistory(readReportHistory(), {
      fetchStatus: getStatus,
      findEntry: findReportHistory,
      saveEntry: upsertReportHistory,
      onChange: () => { if (!cancelled) setHistory(readReportHistory()); },
      isCancelled: () => cancelled,
    }).catch(() => { /* Best effort: a failed re-check leaves the row unchanged. */ });
    return () => { cancelled = true; };
  }, []);

  // Poll all active generating jobs in parallel (multi-job aware).
  useEffect(() => {
    let dead = false, timer;
    const tick = async () => {
      try {
        const jobs = readActiveReports();
        if (!jobs.length) {
          if (!dead) setGenerating([]);
          timer = setTimeout(tick, 2000);
          return;
        }
        const results = await Promise.all(
          jobs.map((j) =>
            getStatus(j.jobId)
              .then((st) => ({ ok: true, job: j, st }))
              .catch((error) => ({ ok: false, job: j, st: null, error }))
          )
        );
        if (dead) return;

        const stillRunning = [];
        const historyAdditions = [];
        for (const r of results) {
          if (!r.ok) {
            if ("error" in r && r.error?.status === 404) {
              removeActiveReport(r.job.jobId);
              toast({
                title: "Report job no longer available",
                description: `${r.job.ticker || "The report"} was lost after a server restart. Start it again when ready.`,
              });
              continue;
            }
            // A failed poll is inconclusive, not proof that the backend job
            // ended. Retain it so the next tick can recover naturally.
            stillRunning.push({
              ...r.job,
              progress: r.job.progress ?? 0,
              step: r.job.step || "Reconnecting",
            });
            continue;
          }
          const { job: j, st } = r;
          if (!st) continue;
          const cleanTicker = sanitizeTicker(st.stock_code || j.ticker || "");
          // Either artifact is enough to promote — a job that finished with
          // only a PDF (no html_file) must not poll forever. Row actions
          // render per-artifact below, so a missing URL just hides its button.
          if ((st.status === "complete" || st.status === "warning") && (st.html_file || st.pdf_file)) {
            removeActiveReport(j.jobId);
            historyAdditions.push({
              jobId: j.jobId,
              ticker: cleanTicker,
              companyName: toLatinName(st.company_name || j.companyName, cleanTicker),
              html: st.html_file ? buildBareDownloadUrl(st.html_file) : null,
              pdf: st.pdf_file ? buildBareDownloadUrl(st.pdf_file) : null,
              finishedAt: st.finished_at || new Date().toISOString(),
              sources: st.sources || [],
              status: st.status,
              warning: st.status === "warning" ? (st.error || st.message || "Report completed with a warning") : null,
            });
          } else if (st.status === "error") {
            removeActiveReport(j.jobId);
            // Failed jobs have no valid research artifact and must not become
            // successful-looking ghost entries in Recent Reports. Surface the
            // terminal failure once before removing it from active tracking.
            toast({
              title: `Report failed${cleanTicker ? ` · ${cleanTicker}` : ""}`,
              description: st.error || st.message || "The report could not be generated.",
            });
            continue;
          } else {
            const previousProgress = Number(j.progress);
            const reportedProgress = Number(st.interpolated_progress ?? st.progress);
            const activeEntry = {
              jobId: j.jobId,
              ticker: cleanTicker,
              companyName: toLatinName(st.company_name || j.companyName, cleanTicker),
              progress: Math.max(
                Number.isFinite(previousProgress) ? previousProgress : 0,
                Number.isFinite(reportedProgress) ? reportedProgress : 0,
              ),
              step: st.step || "Starting",
              eta: st.eta_seconds,
              mode: j.mode,
            };
            stillRunning.push(activeEntry);
            upsertActiveReport(activeEntry);
          }
        }
        if (historyAdditions.length) {
          for (const report of historyAdditions) upsertReportHistory(report);
          setHistory(readReportHistory());
        }
        if (!dead) setGenerating(stillRunning);
        timer = setTimeout(tick, 1500);
      } catch {
        if (!dead) timer = setTimeout(tick, 2500);
      }
    };
    tick();
    return () => { dead = true; if (timer) clearTimeout(timer); };
  }, []);

  const formatDate = (iso) => {
    if (!iso) return "";
    const d = new Date(iso);
    /* Guard against malformed timestamps — `new Date("garbage")` returns
     * an Invalid Date whose `.toLocaleString()` would render the literal
     * string "Invalid Date" to the user. */
    if (isNaN(d.getTime())) return "";
    const now = new Date();
    const diff = now.getTime() - d.getTime();
    if (diff < 0) return "just now";
    if (diff < 60000) return "just now";
    if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
    if (diff < 604800000) return `${Math.floor(diff / 86400000)}d ago`;
    return d.toLocaleString([], { month: "short", day: "numeric" });
  };

  const clearConfirmDeleteTimer = useCallback(() => {
    if (confirmDeleteTimerRef.current) {
      clearTimeout(confirmDeleteTimerRef.current);
      confirmDeleteTimerRef.current = null;
    }
  }, []);

  // First click arms the confirm (revealing a Confirm/Cancel pair); the actual
  // destructive delete only runs on the second, explicit confirm.
  const handleDeleteClick = useCallback((jobId) => {
    clearConfirmDeleteTimer();
    setConfirmDeleteId(jobId);
    confirmDeleteTimerRef.current = setTimeout(() => {
      setConfirmDeleteId(null);
      confirmDeleteTimerRef.current = null;
    }, 4000);
  }, [clearConfirmDeleteTimer]);

  const cancelDelete = useCallback(() => {
    clearConfirmDeleteTimer();
    setConfirmDeleteId(null);
  }, [clearConfirmDeleteTimer]);

  const handleDelete = useCallback(async (jobId) => {
    clearConfirmDeleteTimer();
    setConfirmDeleteId(null);
    try {
      await deleteJob(jobId);
      removeReportHistory(jobId);
      setServerRows((prev) => prev.filter((row) => row?.job_id !== jobId));
      setHistory((prev) => {
        const updated = prev.filter((h) => h.jobId !== jobId);
        return updated;
      });
    } catch (err) {
      toast({ title: "Delete failed", description: err?.message || "The report was not deleted." });
    }
  }, [clearConfirmDeleteTimer]);

  // Disarm any pending confirm timer when the page unmounts.
  useEffect(() => () => clearConfirmDeleteTimer(), [clearConfirmDeleteTimer]);

  const handleView = useCallback((item, e) => {
    const makeInline = (u) => {
      if (!u) return null;
      if (u.includes("inline=1")) return u;
      return u.includes("?") ? `${u}&inline=1` : `${u}?inline=1`;
    };
    const direct = makeInline(item.html) || makeInline(item.pdf) || item.html || item.pdf;
    if (!direct) return;
    const title = toLatinName(item.companyName, item.ticker) || item.ticker;
    // Keep the browser route token-free. ReportViewer attaches the live token
    // only to the actual subresource request, never to history/share URLs.
    const params = new URLSearchParams({ url: safeSameOriginPath(direct), title, jobId: item.jobId });
    navigateWithReveal(`/Viewer?${params.toString()}`, e);
  }, [navigateWithReveal]);

  /*
   * Adaptive morph stagger:
   *  - "chrome" delays (title, subtitle, search, query, generating indicator,
   *    recent header) are fixed offsets from BASE so the above-the-fold
   *    hero always lands within the same window
   *  - the recent report list computes its own stagger via adaptiveStagger
   *    so whether the user has 1 or 50 reports, the full cascade finishes
   *    within ~1.6s
   *  - BASE=0.25 gives a beat of stillness after mount before the reveal,
   *    and also guarantees the animation starts AFTER any CircleTransition
   *    overlay has finished fading out (~560ms), so the morph is always
   *    fully visible regardless of entry route
   */
  const BASE = 0.25;
  const recentCount = recentGroups.length;
  const listStart = generating.length > 0 ? BASE + 0.55 : BASE + 0.42;
  const getRecentDelay = useMemo(
    () => adaptiveStagger(recentCount, { base: listStart, maxTotal: 1.4 }),
    [recentCount, listStart]
  );

  // Once the initial staggered reveal has played, any row inserted afterwards
  // (e.g. a report that finishes generating while the page is open) should slide
  // in almost immediately instead of waiting out the full cascade base delay —
  // otherwise the fresh row sits in its pre-animation state long enough to read
  // as a flash next to the already-settled rows. MorphItem snapshots `delay` on
  // mount, so flipping this after mount only affects newly-mounted rows.
  const initialRevealDoneRef = useRef(false);
  useEffect(() => {
    const t = setTimeout(() => { initialRevealDoneRef.current = true; }, (listStart + 1.4) * 1000);
    return () => clearTimeout(t);
     
  }, []);

  return (
    <main className="minh-screen-dvh" style={{ position: "relative", overflowX: "hidden", width: "100%", background: "#0e1420", color: "#f4f5f7", zIndex: 2 }}>
      <MorphFilters />

      {/* Ambient grain — soft multiply noise over the whole page */}
      <div className="morph-grain" aria-hidden="true" />

      {/* INDAGO PORTAL wordmark + Dashboard menu are now globally rendered
          from Layout.jsx — see that file. */}

      {/* Content */}
      <section
        className="minh-screen-dvh"
        style={{
          position: "relative",
          zIndex: 10,
          display: "flex",
          flexDirection: "column",
          padding: "clamp(6.5rem, 11vh, 8.5rem) clamp(1rem, 3vw, 2rem) clamp(4rem, 8vh, 6rem)",
        }}
      >
        <div style={{ width: "100%", maxWidth: 680, margin: "0 auto" }}>
          {/* page h1 (k4-h1) — the visible "Research" title; inline styles pin the look */}
          <MorphItem
            as="h1"
            delay={BASE}
            duration={1.6}
            maxBlur={48}
            startScale={0.9}
            yOffset={24}
            style={{
              fontFamily: "'Space Grotesk', sans-serif",
              fontSize: "clamp(3rem, 9vw, 7.5rem)",
              fontWeight: 700,
              letterSpacing: "-0.04em",
              margin: "0 0 2rem",
              color: "#f4f5f7",
              textAlign: "center",
              lineHeight: 1.02,
            }}
          >
            Research
          </MorphItem>
          <MorphItem
            delay={BASE + 0.08}
            duration={1.2}
            maxBlur={20}
            yOffset={10}
            startScale={0.96}
            style={{
              display: "flex",
              justifyContent: "center",
              margin: "0 0 2.25rem",
            }}
          >
            <div
              aria-hidden="true"
              style={{
                width: 72,
                height: 2,
                background: "#f4f5f7",
                borderRadius: 2,
              }}
            />
          </MorphItem>
          <MorphItem
            as="p"
            delay={BASE + 0.12}
            duration={1.35}
            maxBlur={28}
            yOffset={16}
            startScale={0.94}
            style={{
              textAlign: "center",
              fontFamily: "'Space Grotesk', sans-serif",
              fontSize: "0.95rem",
              color: "rgba(255,255,255,0.56)",
              fontWeight: 300,
              margin: "0 auto 3rem",
              lineHeight: 1.55,
              maxWidth: 460,
            }}
          >
            Institutional-grade research on every listed company in the USA &mdash; powered by AI
          </MorphItem>

          <MorphItem delay={BASE + 0.22} duration={1.4} maxBlur={32} yOffset={20} startScale={0.94}>
            <SearchBar reportHistory={recentRows} />
          </MorphItem>

          {/* Query link */}
          <MorphItem
            delay={BASE + 0.32}
            duration={1.2}
            maxBlur={22}
            yOffset={14}
            startScale={0.95}
            style={{ display: "flex", justifyContent: "center", marginTop: "1.2rem" }}
          >
            <button
              type="button"
              onClick={(e) => navigateWithReveal("/DeepResearch", e)}
              aria-label="Open Callisto"
              style={{
                fontFamily: "'Space Grotesk', sans-serif",
                fontSize: "0.6rem",
                fontWeight: 500,
                letterSpacing: "0.18em",
                textTransform: "uppercase",
                color: "rgba(255,255,255,0.42)",
                background: "none",
                border: "none",
                cursor: "pointer",
                padding: "5px 10px",
                borderRadius: 6,
                transition: "all 0.2s ease",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.color = "rgba(255,255,255,0.75)";
                e.currentTarget.style.background = "rgba(255,255,255,0.06)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.color = "rgba(255,255,255,0.42)";
                e.currentTarget.style.background = "none";
              }}
            >
              Callisto
            </button>
          </MorphItem>

          {/* Active generating indicators (multi-job) */}
          {generating.map((g, gi) => (
            <MorphItem key={g.jobId} delay={BASE + 0.4 + gi * 0.05} duration={1.3} maxBlur={28} yOffset={18} startScale={0.95} style={{ marginTop: gi === 0 ? "2.5rem" : "0.75rem" }}>
            <button
              type="button"
              onClick={(e) => {
                const p = new URLSearchParams({
                  jobId: g.jobId,
                  ticker: g.ticker,
                  name: toLatinName(g.companyName, g.ticker),
                  mode: g.mode || "full",
                });
                navigateWithReveal(`/GenerateReport?${p.toString()}`, e);
              }}
              style={{
                width: "100%",
                background: "rgba(255,255,255,0.05)",
                border: "1px solid rgba(255,255,255,0.12)",
                borderRadius: 14,
                padding: "16px 20px",
                cursor: "pointer",
                position: "relative",
                overflow: "hidden",
                textAlign: "left",
                transition: "border-color 0.3s ease, box-shadow 0.3s ease",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = "rgba(255,255,255,0.22)";
                e.currentTarget.style.boxShadow = "0 4px 20px rgba(255,255,255,0.25)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = "rgba(255,255,255,0.12)";
                e.currentTarget.style.boxShadow = "none";
              }}
            >
              {/* Progress bar background */}
              <div
                style={{
                  position: "absolute",
                  top: 0,
                  left: 0,
                  height: "100%",
                  width: `${g.progress}%`,
                  background: "linear-gradient(90deg, rgba(255,255,255,0.03) 0%, rgba(255,255,255,0.06) 100%)",
                  transition: "width 1.2s cubic-bezier(0.16,1,0.3,1)",
                  borderRadius: 14,
                }}
              />
              {/* Shimmer overlay */}
              <div
                style={{
                  position: "absolute",
                  top: 0,
                  left: 0,
                  width: "100%",
                  height: "100%",
                  background: "linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.05) 50%, transparent 100%)",
                  backgroundSize: "200% 100%",
                  animation: "shimmer 2s ease-in-out infinite",
                  borderRadius: 14,
                }}
              />
              <style>{`@keyframes shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }`}</style>
              {/* Content */}
              <div style={{ position: "relative", zIndex: 1, display: "flex", alignItems: "center", gap: 14 }}>
                {/* Pulsing dot */}
                <div style={{ position: "relative", width: 10, height: 10, flexShrink: 0 }}>
                  <div
                    style={{
                      width: 10,
                      height: 10,
                      borderRadius: "50%",
                      background: "#f4f5f7",
                      animation: "pulse-dot 2s ease-in-out infinite",
                    }}
                  />
                  <div
                    style={{
                      position: "absolute",
                      top: -3,
                      left: -3,
                      width: 16,
                      height: 16,
                      borderRadius: "50%",
                      border: "1.5px solid rgba(255,255,255,0.3)",
                      animation: "pulse-ring 2s ease-in-out infinite",
                    }}
                  />
                  <style>{`
                    @keyframes pulse-dot { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.6; transform: scale(0.85); } }
                    @keyframes pulse-ring { 0%, 100% { opacity: 0.4; transform: scale(1); } 50% { opacity: 0; transform: scale(1.8); } }
                  `}</style>
                </div>
                {/* Text */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span
                      style={{
                        fontFamily: "'Space Grotesk', sans-serif",
                        fontSize: "0.8rem",
                        fontWeight: 500,
                        color: "#f4f5f7",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {toLatinName(g.companyName, g.ticker) || g.ticker}
                    </span>
                    <span
                      style={{
                        fontFamily: "'Space Grotesk', sans-serif",
                        fontSize: "0.65rem",
                        fontWeight: 500,
                        color: "#f4f5f7",
                        letterSpacing: "0.05em",
                        flexShrink: 0,
                      }}
                    >
                      {g.ticker}
                    </span>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 3 }}>
                    <span
                      style={{
                        fontFamily: "'Space Grotesk', sans-serif",
                        fontSize: "0.65rem",
                        fontWeight: 500,
                        color: "rgba(255,255,255,0.7)",
                        letterSpacing: "0.08em",
                        textTransform: "uppercase",
                      }}
                    >
                      Generating
                    </span>
                    <span
                      style={{
                        fontFamily: "'Space Grotesk', sans-serif",
                        fontSize: "0.65rem",
                        fontWeight: 400,
                        color: "rgba(255,255,255,0.56)",
                        minWidth: 0,
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {g.step} — {Math.round(g.progress)}%
                    </span>
                    {g.eta != null && g.eta > 0 && (
                      <span
                        style={{
                          fontFamily: "'Space Grotesk', sans-serif",
                          fontSize: "0.65rem",
                          fontWeight: 400,
                          color: "rgba(255,255,255,0.25)",
                          fontVariantNumeric: "tabular-nums",
                        }}
                      >
                        ~{Math.floor(g.eta / 60)}:{String(Math.floor(g.eta % 60)).padStart(2, "0")}
                      </span>
                    )}
                  </div>
                </div>
                {/* Arrow */}
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none" style={{ flexShrink: 0, opacity: 0.2 }}>
                  <path d="M5 3l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </div>
              {/* Bottom progress line */}
              <div
                style={{
                  position: "absolute",
                  bottom: 0,
                  left: 0,
                  height: 2,
                  width: `${g.progress}%`,
                  background: "linear-gradient(90deg, rgba(255,255,255,0.9), rgba(255,255,255,0.45))",
                  borderRadius: "0 0 14px 14px",
                  transition: "width 1.2s cubic-bezier(0.16,1,0.3,1)",
                }}
              />
            </button>
            </MorphItem>
          ))}

          {/* Recent reports */}
          {recentRows.length > 0 && (
            <div style={{ marginTop: generating.length > 0 ? "1.5rem" : "3rem" }}>
              <MorphItem
                as="span"
                delay={BASE + 0.36}
                duration={1.15}
                maxBlur={20}
                yOffset={12}
                startScale={0.95}
                style={{
                  display: "block",
                  fontFamily: "'Space Grotesk', sans-serif",
                  fontSize: "0.6rem",
                  textTransform: "uppercase",
                  letterSpacing: "0.25em",
                  color: "rgba(255,255,255,0.56)",
                  fontWeight: 500,
                  marginBottom: "1rem",
                }}
              >
                Recent
              </MorphItem>
              <style>{`@media (prefers-reduced-motion: reduce) { .rr-recent-main { transform: none !important; transition: none !important; } }`}</style>
              <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
                {recentGroups.map(({ item, runs }, idx) => {
                  const isHov = hoveredItem === item.jobId;
                  const latinName = toLatinName(item.companyName, item.ticker);
                  const isViewable = !!(item.html || item.pdf);
                  const warningText = item.warning || (item.status === "warning" ? "Report completed with a warning." : null);
                  // A server row carries only the count; the list loads on open.
                  const sourceCount = Math.max(item.sources?.length || 0, item.sourceCount || 0);
                  return (
                    <MorphItem
                      key={item.jobId}
                      as="li"
                      delay={initialRevealDoneRef.current ? 0.02 : getRecentDelay(idx)}
                      duration={1.25}
                      maxBlur={26}
                      yOffset={16}
                      startScale={0.95}
                      style={{
                        borderTop: "1px solid rgba(255,255,255,0.1)",
                      }}
                    >
                      <div
                        className="rr-recent-row"
                        style={{
                          display: "flex",
                          alignItems: "center",
                          padding: "0.85rem 0",
                          cursor: "default",
                        }}
                        onMouseEnter={() => setHoveredItem(item.jobId)}
                        onMouseLeave={() => setHoveredItem(null)}
                        onFocusCapture={() => setHoveredItem(item.jobId)}
                        onBlurCapture={(e) => {
                          if (!e.currentTarget.contains(e.relatedTarget)) setHoveredItem(null);
                        }}
                      >
                      {/* Name / ticker / time — clickable opens the report when
                          one is available; otherwise it carries no clickable
                          affordance so the cursor/role never lies. */}
                      <div
                        {...(isViewable
                          ? {
                              role: "button",
                              tabIndex: 0,
                              "aria-label": runs > 1
                                ? `Open latest report for ${latinName} (${runs} runs)`
                                : `Open report for ${latinName}`,
                              onClick: (e) => handleView(item, e),
                              onKeyDown: (e) => {
                                if (e.key === "Enter" || e.key === " ") {
                                  e.preventDefault();
                                  handleView(item, e);
                                }
                              },
                            }
                          : {})}
                        className="rr-recent-main"
                        style={{
                          display: "flex",
                          alignItems: "center",
                          flex: 1,
                          minWidth: 0,
                          cursor: isViewable ? "pointer" : "default",
                          // Only the name/ticker/time block slides on hover; the
                          // actions (View, Download, Delete) stay put under the cursor.
                          transition: "transform 0.4s cubic-bezier(0.16,1,0.3,1)",
                          transform: isHov ? "translateX(6px)" : "translateX(0)",
                          outline: isViewable ? "2px solid transparent" : "none",
                          outlineOffset: 4,
                        }}
                        onFocus={(e) => { if (isViewable) e.currentTarget.style.outlineColor = "rgba(255,255,255,0.55)"; }}
                        onBlur={(e) => { e.currentTarget.style.outlineColor = "transparent"; }}
                      >
                      {/* Company name, then the runs and warning badges in the same
                          flexible slot, so the ticker and time columns stay
                          aligned whether or not a row has a badge. The warning
                          reason sits on a muted second line (touch has no title
                          tooltip). */}
                      <span
                        style={{
                          display: "flex",
                          flexDirection: "column",
                          flex: 1,
                          minWidth: 0,
                          marginRight: "0.75rem",
                        }}
                      >
                      <span
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 8,
                          minWidth: 0,
                        }}
                      >
                        <span
                          style={{
                            fontFamily: "'Space Grotesk', sans-serif",
                            fontSize: "0.85rem",
                            fontWeight: 500,
                            color: "#f4f5f7",
                            minWidth: 0,
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                          }}
                        >
                          {latinName}
                        </span>
                        {runs > 1 && (
                          <span
                            className="rr-recent-runs"
                            title={`${runs} runs of ${latinName}; this row opens the latest`}
                            style={{
                              fontSize: "0.72rem",
                              lineHeight: 1,
                              color: isHov ? "#f4f5f7" : "rgba(255,255,255,0.42)",
                              transition: "color 0.2s ease",
                              whiteSpace: "nowrap",
                              flexShrink: 0,
                            }}
                          >
                            ×{runs} runs
                          </span>
                        )}
                        {warningText && (
                          <span
                            role="status"
                            aria-label={`Report warning: ${warningText}`}
                            title={warningText}
                            style={{
                              fontFamily: "'Space Grotesk', sans-serif",
                              fontSize: "0.58rem",
                              fontWeight: 600,
                              color: "#fcd34d",
                              background: "rgba(245,158,11,0.14)",
                              border: "1px solid rgba(251,191,36,0.32)",
                              borderRadius: 999,
                              padding: "2px 6px",
                              flexShrink: 0,
                            }}
                          >
                            {item.pdf ? "Warning" : "HTML only"}
                          </span>
                        )}
                      </span>
                      {warningText && (
                        <span
                          aria-hidden="true"
                          title={warningText}
                          style={{
                            fontFamily: "'Space Grotesk', sans-serif",
                            fontSize: "0.68rem",
                            fontWeight: 400,
                            lineHeight: 1.35,
                            color: "rgba(255,255,255,0.5)",
                            marginTop: 2,
                            minWidth: 0,
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                          }}
                        >
                          {warningText}
                        </span>
                      )}
                      </span>

                      {/* Ticker */}
                      <span
                        style={{
                          fontFamily: "'Space Grotesk', sans-serif",
                          fontSize: "0.7rem",
                          fontWeight: 500,
                          color: "#f4f5f7",
                          letterSpacing: "0.05em",
                          marginRight: "1rem",
                          flexShrink: 0,
                          width: 48,
                          textAlign: "right",
                        }}
                      >
                        {item.ticker}
                      </span>

                      {/* Time */}
                      <span
                        style={{
                          fontFamily: "'Space Grotesk', sans-serif",
                          fontSize: "0.7rem",
                          color: "rgba(255,255,255,0.56)",
                          fontWeight: 300,
                          marginRight: "1rem",
                          flexShrink: 0,
                          width: 64,
                          textAlign: "left",
                        }}
                      >
                        {formatDate(item.finishedAt)}
                      </span>
                      </div>

                      {/* Actions — hover-revealed on desktop, always shown on touch */}
                      <div
                        className="rr-recent-actions"
                        style={{
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "flex-end",
                          gap: 4,
                          opacity: (isHov || coarsePointer || confirmDeleteId === item.jobId) ? 1 : 0,
                          transition: "opacity 0.2s ease",
                          flexShrink: 0,
                          // Wide enough for every action with a three-digit source
                          // count, so the ticker and time columns never move.
                          minWidth: 172,
                        }}
                      >
                        {sourceCount > 0 && (
                          <button
                            type="button"
                            aria-label={`View ${sourceCount} sources`}
                            title={`View ${sourceCount} sources`}
                            onClick={() => {
                              activeSourcesJob.current = item.jobId;
                              setActiveSources(item.sources || []);
                              setActiveCompany(toLatinName(item.companyName, item.ticker));
                              setSourcesOpen(true);
                              // Refresh sources from backend (localStorage may have stale/incomplete data)
                              getStatus(item.jobId)
                                .then((st) => {
                                  // Ignore a late resolve if the modal has since been
                                  // opened for (or closed away from) a different report.
                                  if (activeSourcesJob.current !== item.jobId) return;
                                  if (st?.sources?.length && st.sources.length > (item.sources || []).length) {
                                    setActiveSources(st.sources);
                                    upsertReportHistory({ ...item, sources: st.sources });
                                    setHistory(readReportHistory());
                                  }
                                })
                                .catch(() => {}); // Backend may not have this job anymore — keep localStorage data
                            }}
                            style={{
                              background: "none",
                              border: "none",
                              cursor: "pointer",
                              padding: "4px 6px",
                              borderRadius: 4,
                              color: "rgba(255,255,255,0.56)",
                              display: "inline-flex",
                              alignItems: "center",
                              gap: 3,
                              fontSize: "0.65rem",
                              fontFamily: "'Space Grotesk', sans-serif",
                              fontVariantNumeric: "tabular-nums",
                              transition: "color 0.15s ease",
                            }}
                            onMouseEnter={(e) => { e.currentTarget.style.color = "rgba(255,255,255,0.7)"; }}
                            onMouseLeave={(e) => { e.currentTarget.style.color = "rgba(255,255,255,0.56)"; }}
                          >
                            <BookOpen size={12} aria-hidden="true" />
                            {sourceCount}
                          </button>
                        )}

                        {(item.html || item.pdf) && (
                          <button
                            type="button"
                            onClick={(e) => handleView(item, e)}
                            style={{
                              background: "none",
                              border: "none",
                              cursor: "pointer",
                              padding: "4px 8px",
                              borderRadius: 4,
                              color: "rgba(255,255,255,0.46)",
                              display: "inline-flex",
                              alignItems: "center",
                              gap: 3,
                              fontSize: "0.65rem",
                              fontFamily: "'Space Grotesk', sans-serif",
                              fontWeight: 500,
                              transition: "all 0.15s ease",
                            }}
                            onMouseEnter={(e) => {
                              e.currentTarget.style.background = "#f4f5f7";
                              e.currentTarget.style.color = "#0e1420";
                            }}
                            onMouseLeave={(e) => {
                              e.currentTarget.style.background = "none";
                              e.currentTarget.style.color = "rgba(255,255,255,0.46)";
                            }}
                          >
                            View <ArrowUpRight size={10} />
                          </button>
                        )}

                        {item.pdf && (
                          <a
                            href={safeSameOriginPath(item.pdf)}
                            target="_blank"
                            rel="noreferrer"
                            aria-label={`Download PDF for ${toLatinName(item.companyName, item.ticker)}`}
                            title="Download PDF"
                            style={{
                              color: "rgba(255,255,255,0.46)",
                              padding: "4px 6px",
                              borderRadius: 4,
                              display: "inline-flex",
                              textDecoration: "none",
                              transition: "color 0.15s ease",
                            }}
                            onMouseEnter={(e) => { e.currentTarget.style.color = "rgba(255,255,255,0.6)"; }}
                            onMouseLeave={(e) => { e.currentTarget.style.color = "rgba(255,255,255,0.46)"; }}
                          >
                            <Download size={12} />
                          </a>
                        )}

                        {/* Destructive control — separated from View/Download by a
                            margin and gated behind an explicit two-step confirm so
                            an accidental tap can't irreversibly purge the report. */}
                        {confirmDeleteId === item.jobId ? (
                          <div style={{ display: "inline-flex", alignItems: "center", gap: 4, marginLeft: 6 }}>
                            <button
                              type="button"
                              onClick={cancelDelete}
                              aria-label="Cancel delete"
                              style={{
                                background: "none",
                                border: "none",
                                cursor: "pointer",
                                padding: "4px 8px",
                                borderRadius: 4,
                                color: "rgba(255,255,255,0.56)",
                                display: "inline-flex",
                                alignItems: "center",
                                fontSize: "0.65rem",
                                fontFamily: "'Space Grotesk', sans-serif",
                                fontWeight: 500,
                                transition: "all 0.15s ease",
                              }}
                              onMouseEnter={(e) => { e.currentTarget.style.color = "rgba(255,255,255,0.7)"; }}
                              onMouseLeave={(e) => { e.currentTarget.style.color = "rgba(255,255,255,0.56)"; }}
                            >
                              Cancel
                            </button>
                            <button
                              type="button"
                              onClick={() => handleDelete(item.jobId)}
                              aria-label={runs > 1 ? `Confirm delete latest report for ${latinName}` : `Confirm delete report for ${latinName}`}
                              style={{
                                background: "#cc3333",
                                border: "none",
                                cursor: "pointer",
                                padding: "6px 10px",
                                borderRadius: 6,
                                color: "#fff",
                                display: "inline-flex",
                                alignItems: "center",
                                gap: 4,
                                fontSize: "0.65rem",
                                fontFamily: "'Space Grotesk', sans-serif",
                                fontWeight: 600,
                                transition: "all 0.15s ease",
                              }}
                              onMouseEnter={(e) => { e.currentTarget.style.background = "#b32d2d"; }}
                              onMouseLeave={(e) => { e.currentTarget.style.background = "#cc3333"; }}
                            >
                              <Trash2 size={12} /> Delete
                            </button>
                          </div>
                        ) : (
                          <button
                            type="button"
                            onClick={() => handleDeleteClick(item.jobId)}
                            aria-label={runs > 1 ? `Delete latest report for ${latinName}` : `Delete report for ${latinName}`}
                            title={runs > 1 ? "Delete this run (older runs stay)" : "Delete"}
                            style={{
                              background: "none",
                              border: "none",
                              cursor: "pointer",
                              padding: "6px 8px",
                              borderRadius: 6,
                              color: "rgba(255,255,255,0.3)",
                              display: "inline-flex",
                              marginLeft: 6,
                              transition: "all 0.15s ease",
                            }}
                            onMouseEnter={(e) => {
                              e.currentTarget.style.color = "#f87171";
                              e.currentTarget.style.background = "rgba(248,113,113,0.12)";
                            }}
                            onMouseLeave={(e) => {
                              e.currentTarget.style.color = "rgba(255,255,255,0.3)";
                              e.currentTarget.style.background = "none";
                            }}
                          >
                            <Trash2 size={14} />
                          </button>
                        )}
                      </div>
                      </div>
                    </MorphItem>
                  );
                })}
              </ul>
            </div>
          )}

          {/* Empty state */}
          {recentRows.length === 0 && serverListSettled && (
            <MorphItem
              delay={BASE + 0.44}
              duration={1.35}
              maxBlur={26}
              yOffset={16}
              startScale={0.95}
              style={{ marginTop: "4rem", textAlign: "center" }}
            >
              <Search size={22} style={{ color: "rgba(255,255,255,0.22)", margin: "0 auto 14px", display: "block" }} />
              <p style={{ fontFamily: "'Space Grotesk', sans-serif", fontSize: "0.85rem", color: "rgba(255,255,255,0.56)", fontWeight: 300 }}>
                Search to generate your first report
              </p>
            </MorphItem>
          )}
        </div>
      </section>

      <SourcesModal
        isOpen={sourcesOpen}
        onClose={() => { activeSourcesJob.current = null; setSourcesOpen(false); }}
        sources={activeSources}
        companyName={activeCompany}
      />
    </main>
  );
}

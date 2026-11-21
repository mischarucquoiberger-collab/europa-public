import React, { useEffect, useMemo, useRef, useState } from "react";
import { motion, AnimatePresence, useReducedMotion } from "framer-motion";
import {
  ArrowLeft, Building2,
  Check, Loader2, Download, ExternalLink, X, Plus,
  Share2, RotateCcw, Database, BarChart3, Brain, Sparkles,
  PanelLeftClose, PanelLeftOpen, BookOpen, FileText,
} from "lucide-react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { startReport, getStatus, buildDownloadUrl, buildViewUrl, buildBareDownloadUrl } from "@/api/backend";
import { safeSameOriginPath } from "@/lib/safeUrl";
import { copyReportShareLink, reportViewerPath } from "@/lib/reportShareLink";
import { toast } from "@/components/ui/use-toast";
import SourcesModal from "@/components/report/SourcesModal";
import { reportProgress } from "@/lib/reportProgress";
import {
  createReportStorage,
  normalizeJobId,
} from "@/lib/reportStorage";

/* ── Pipeline ─────────────────────────────────────────────── */
const PIPELINE = [
  { key: "Starting", icon: Sparkles,  label: "Initializing" },
  { key: "Company Info",  icon: Building2, label: "Company Info" },
  { key: "Data Fetch",    icon: Database,  label: "Data Fetch" },
  { key: "Extraction",    icon: FileText,  label: "Extraction" },
  { key: "Analysis",      icon: BarChart3, label: "Analysis" },
  { key: "Valuation",     icon: BarChart3, label: "Valuation" },
  { key: "Peers",         icon: BarChart3, label: "Compare Peers" },
  { key: "Drafting",      icon: Brain,     label: "Drafting" },
  { key: "Rendering",     icon: FileText,  label: "Rendering" },
  { key: "Complete",      icon: Check,     label: "Complete" },
];

const fmtTime = (s) => {
  if (s == null || Number.isNaN(s)) return "--:--";
  return `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
};

/** The progress percentage to show for a status: interpolated_progress when sent, else the reported milestone. */
export function shownProgress(status, reported = 0) {
  const raw = status?.interpolated_progress;
  if (typeof raw === "number" && Number.isFinite(raw)) return Math.min(100, Math.max(0, raw));
  return reported;
}

/* ── spring curve ── */
const ease = [0.16, 1, 0.3, 1];

// Known-symbol English name overrides for large US companies (the same table
// as in Home.jsx). Keeps display consistent when a stored or reported name is
// in another script.
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

// Always return a Latin-only company name for the given ticker.
const toLatinName = (name, ticker) => {
  const t = ticker ? String(ticker).trim() : "";
  if (!name) return KNOWN_EN_NAMES[t] || t;
  const str = String(name);
  if (!CJK_RE.test(str)) return str;
  if (KNOWN_EN_NAMES[t]) return KNOWN_EN_NAMES[t];
  const cleaned = str
    .replace(/[\u3000-\u303F\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF\uFF00-\uFFEF]/g, "")
    .replace(/\s+/g, " ")
    .trim();
  return cleaned || t;
};

// Strip anything that isn't a valid ticker character and show the symbol in
// capitals (US symbols: letters plus a class suffix such as BRK.B or BF-B).
// Takes the first whitespace/comma-separated token so a legacy URL or
// localStorage entry like "aapl, apple" collapses to "AAPL" instead of
// "AAPLAPPLE". This protects against old entries that would otherwise show the
// same string in both the company-name span and the ticker span.
const sanitizeTicker = (raw) => {
  const s = String(raw || "").trim();
  if (!s) return "";
  const first = s.split(/[\s,]+/)[0] || s;
  return first.replace(/[^0-9A-Za-z.-]/g, "").slice(0, 10).toUpperCase();
};

const parseRouteRequest = (search) => {
  const multi = search.get("tickers");
  let queue;
  if (multi) {
    const seen = new Set();
    queue = multi
      .split(",")
      .map(sanitizeTicker)
      .filter((t) => t && !seen.has(t) && seen.add(t));
  } else {
    const one = sanitizeTicker(search.get("ticker") || "");
    queue = one ? [one] : [];
  }
  const requestedIdx = parseInt(search.get("qi") || "0", 10);
  const safeIdx = Number.isFinite(requestedIdx) && requestedIdx >= 0 ? requestedIdx : 0;
  const queueIdx = Math.min(safeIdx, Math.max(queue.length - 1, 0));
  const ticker = queue[queueIdx] || sanitizeTicker(search.get("ticker") || "");
  const requestedJobId = search.get("jobId");
  const jobId = normalizeJobId(requestedJobId);
  return {
    queue,
    queueIdx,
    ticker,
    companyName: toLatinName(search.get("name") || "", ticker),
    mode: search.get("mode") || "full",
    jobId,
    jobIdRequested: requestedJobId !== null,
    invalidJobId: requestedJobId !== null && !jobId,
  };
};

/* ── Component ────────────────────────────────────────────── */
export default function GenerateReport() {
  const [{ findReportHistory, removeActiveReport, upsertActiveReport, upsertReportHistory }] = useState(createReportStorage);
  const location = useLocation();
  const navigate = useNavigate();
  const search = useMemo(() => new URLSearchParams(location.search), [location.search]);
  const routeRequest = useMemo(() => parseRouteRequest(search), [search]);

  // Entry points: single report uses ?ticker= ; the screener Export "Batch
  // reports" and Compare "Generate reports for all N" navigate with ?tickers=A,B,C
  // (Export also adds &batch=1). Keep the parsed request in state because batch
  // controls advance it locally, then re-apply a genuinely new query string so
  // same-route command-palette/browser-history navigation cannot retain another
  // company's job behind a newly changed address bar.
  const [queue, setQueue] = useState(routeRequest.queue);
  const [queueIdx, setQueueIdx] = useState(routeRequest.queueIdx);
  const [ticker, setTicker] = useState(routeRequest.ticker);
  const [companyName, setCompanyName] = useState(routeRequest.companyName);
  const [mode, setMode] = useState(routeRequest.mode);
  const [jobId, setJobId] = useState(routeRequest.jobId);
  const [autoStartAllowed, setAutoStartAllowed] = useState(!routeRequest.jobIdRequested);
  const [status, setStatus] = useState(null);
  const [isStarting, setIsStarting] = useState(false);
  const [error, setError] = useState(null);
  const [showSources, setShowSources] = useState(false);
  // Report-preview iframe load/error state (skeleton shown until onLoad fires).
  const [previewLoaded, setPreviewLoaded] = useState(false);
  const [previewError, setPreviewError] = useState(false);

  const contentRef = useRef(null);
  // Ready-state entrance (owner 11-22): one short fade, nothing that sweeps,
  // bounces or travels; with prefers-reduced-motion it appears with no entrance.
  const reduceMotion = useReducedMotion();
  const readyEnter = reduceMotion ? false : { opacity: 0 };
  const readyFade = { duration: 0.2, ease: "easeOut" };
  // Leaving the running/error state is a plain quick fade (it used to shrink and
  // blur for 0.6 s, which held the ready state back under AnimatePresence "wait").
  const stateExit = { opacity: 0, transition: { duration: reduceMotion ? 0 : 0.15 } };

  // UI state
  // On phones the sidebar must not push the running content into a sliver: start
  // it closed below 768px and render it as an overlay (handled in JSX) when opened.
  const [isMobile, setIsMobile] = useState(() => typeof window !== "undefined" && window.innerWidth < 768);
  const [sidebarOpen, setSidebarOpen] = useState(() => typeof window === "undefined" || window.innerWidth >= 768);
  useEffect(() => {
    const onResize = () => {
      const mobile = window.innerWidth < 768;
      setIsMobile(mobile);
      // Narrowing past 768px: collapse the sidebar so it doesn't squeeze the
      // content into a sliver (it reopens as an overlay on mobile).
      if (mobile) setSidebarOpen(false);
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  // Mobile drawer focus contract (audit P-07): focus moves into the dialog on
  // open (making its Escape handler reachable) and back to the opener on close;
  // the background is inert while it is up. Desktop path untouched.
  const sidebarRef = useRef(null);
  const sidebarTriggerRef = useRef(null);
  useEffect(() => {
    if (isMobile && sidebarOpen) {
      sidebarTriggerRef.current = document.activeElement;
      sidebarRef.current?.focus();
    } else if (isMobile && sidebarTriggerRef.current) {
      if (document.contains(sidebarTriggerRef.current)) sidebarTriggerRef.current.focus();
      sidebarTriggerRef.current = null;
    }
  }, [isMobile, sidebarOpen]);
  const statusReceivedAtRef = useRef(0);
  const progressView = reportProgress(status, {
    receivedAt: statusReceivedAtRef.current, hasError: Boolean(error),
  });
  const stageMsg = progressView.message;
  const eta = progressView.etaSeconds;

  // The same number as the Reports card (Home.jsx): the backend's
  // interpolated_progress when it sends one (it moves inside a step and is never
  // below progress), else progress. maxPctRef keeps the shown number from ever
  // going down, as the card does.
  const maxPctRef = useRef(0);
  const rawPct = shownProgress(status, progressView.progress);
  if (rawPct > maxPctRef.current) maxPctRef.current = rawPct;
  const pct = maxPctRef.current;
  const step = status?.step || "Starting";
  const maxStepRef = useRef(0);
  const rawIdx = PIPELINE.findIndex((p) => p.key === step);
  if (rawIdx >= 0 && rawIdx > maxStepRef.current) maxStepRef.current = rawIdx;
  const stepIdx = rawIdx >= 0 ? rawIdx : maxStepRef.current;
  const routeVersionRef = useRef(0);
  const appliedRouteRef = useRef(null);
  const mountedRef = useRef(false);
  const pendingStartRef = useRef(null);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  useEffect(() => {
    // Strict Mode replays setup/cleanup without a new route. Keep that replay
    // attached to the original POST instead of discarding it or paying twice.
    if (appliedRouteRef.current === routeRequest) return;
    appliedRouteRef.current = routeRequest;
    routeVersionRef.current += 1;
    setQueue(routeRequest.queue);
    setQueueIdx(routeRequest.queueIdx);
    setTicker(routeRequest.ticker);
    setCompanyName(routeRequest.companyName);
    setMode(routeRequest.mode);
    setJobId(routeRequest.jobId);
    setAutoStartAllowed(!routeRequest.jobIdRequested);
    setStatus(routeRequest.invalidJobId
      ? { status: "error", error: "This report link contains an invalid job ID." }
      : null);
    setError(routeRequest.invalidJobId ? "This report link contains an invalid job ID." : null);
    setIsStarting(false);
    setShowSources(false);
    statusReceivedAtRef.current = 0;
    maxPctRef.current = 0;
    maxStepRef.current = 0;
  }, [routeRequest]);

  const isComplete = status?.status === "complete" || status?.status === "warning" || step === "Complete";
  const isError = status?.status === "error";
  const isQueued = status?.status === "queued";
  const isWarning = status?.status === "warning";
  const warningMessage = isWarning
    ? (status?.error || status?.message || "One or more report artifacts could not be generated.")
    : null;
  // No company to generate (bare /GenerateReport with no ?ticker/?tickers). Show
  // an empty state instead of an endless "Loading..." orb (and never auto-start a
  // default company).
  const noTarget = !ticker && !jobId;
  const isRunning = !isComplete && !isError && !noTarget;
  const hasNextInQueue = queueIdx < queue.length - 1;
  // A job without a separate company name (an unknown symbol such as ZZZZ, or
  // before the backend supplies it) shows its ticker once, not "ZZZZ / ZZZZ".
  const headerName = companyName && companyName.toUpperCase() !== String(ticker || "").toUpperCase() ? companyName : ticker;
  // Keep one monotonic elapsed origin across queue wait and execution. Prefer
  // created_at once the server provides it; falling back to started_at keeps
  // compatibility with older saved status payloads without resetting the
  // visible timer backwards when a queued job acquires a worker.
  const createdAt = status?.created_at || status?.started_at;
  const finishedAt = status?.finished_at;
  const [elapsed, setElapsed] = useState(null);

  // Auto-collapse sidebar on completion
  useEffect(() => {
    if (isComplete) setSidebarOpen(false);
  }, [isComplete]);

  // Each report owns a separate storage record. Updating this job can therefore
  // never overwrite a report started or completed in another browser tab.
  useEffect(() => {
    if (!jobId) return;

    if (isRunning) {
      const cleanTicker = sanitizeTicker(ticker);
      upsertActiveReport({
        jobId,
        ticker: cleanTicker,
        companyName: toLatinName(companyName, cleanTicker),
        startedAt: createdAt,
        mode,
        progress: pct,
        step,
        eta: status?.eta_seconds,
      });
    } else if (isComplete || isError) {
      removeActiveReport(jobId);
    }
  }, [jobId, isRunning, isComplete, isError, ticker, companyName, createdAt, mode, pct, step, status?.eta_seconds]);

  // 1-second interval to keep elapsed timer ticking during the run
  useEffect(() => {
    if (!createdAt) { setElapsed(null); return; }
    const update = () => {
      const end = finishedAt ? new Date(finishedAt) : new Date();
      setElapsed(Math.max(0, Math.floor((end.getTime() - new Date(createdAt).getTime()) / 1000)));
    };
    update();
    if (finishedAt) return;
    const iv = setInterval(update, 1000);
    return () => clearInterval(iv);
  }, [createdAt, finishedAt]);

  const downloadHtml = buildDownloadUrl(status?.html_file);
  const downloadPdf = buildDownloadUrl(status?.pdf_file);
  const viewHtml = buildViewUrl(status?.html_file);

  // Reset the preview skeleton/error whenever the previewed report changes so a
  // new report shows the loading skeleton instead of a stale loaded/error state.
  useEffect(() => {
    setPreviewLoaded(false);
    setPreviewError(false);
  }, [viewHtml]);

  /* ── Start job ── */
  const startNewJob = async () => {
    if (!ticker || !mountedRef.current) return;
    const routeVersion = routeVersionRef.current;
    // State updates are asynchronous; this also blocks rapid double clicks and
    // the initial auto-start effect's Strict Mode replay from issuing two POSTs.
    if (pendingStartRef.current?.routeVersion === routeVersion) return;
    const pendingStart = { routeVersion };
    pendingStartRef.current = pendingStart;
    const isCurrentStart = () => mountedRef.current && routeVersion === routeVersionRef.current;
    const previousJobId = jobId;
    if (previousJobId) removeActiveReport(previousJobId);
    // Retire the previous identity before starting. A late status poll is then
    // cleaned up and cannot write old-company state over the replacement job.
    setJobId(null);
    setAutoStartAllowed(false);
    setIsStarting(true);
    setError(null);
    setStatus(null);
    statusReceivedAtRef.current = 0;
    maxPctRef.current = 0;
    maxStepRef.current = 0;
    try {
      const res = await startReport({ stock_code: ticker, company_name: companyName, mode });
      const id = normalizeJobId(res?.job_id);
      if (!id) throw new Error("Job ID missing");
      // Leaving this page does not cancel an accepted server job. Retain its
      // independent record for Home, but never navigate or set stale UI state.
      upsertActiveReport({ jobId: id, ticker, companyName, mode });
      if (!isCurrentStart()) return;
      setJobId(id);
      const p = new URLSearchParams({ jobId: id, ticker, name: companyName || "", mode });
      // Keep the batch queue in the URL so a mid-batch reload resumes correctly.
      if (queue.length > 1) { p.set("tickers", queue.join(",")); p.set("qi", String(queueIdx)); }
      navigate(`/GenerateReport?${p.toString()}`, { replace: true });
    } catch (err) {
      if (!isCurrentStart()) return;
      // Surface a terminal error state too — otherwise the UI sits in a
      // perpetual spinning "running" view with no indication the start failed.
      setError(err.message || "Failed to start");
      setStatus({ status: "error", error: err.message || "Failed to start" });
    } finally {
      if (pendingStartRef.current === pendingStart) pendingStartRef.current = null;
      if (isCurrentStart()) setIsStarting(false);
    }
  };

  // Advance the batch queue to a given index and kick off that company's report.
  // Resets job/status to null so the auto-start effect fires for the new ticker.
  const startQueueItem = (idx) => {
    if (idx < 0 || idx >= queue.length) return;
    const t = queue[idx];
    if (!t) return;
    routeVersionRef.current += 1;
    setQueueIdx(idx);
    setTicker(t);
    setCompanyName(toLatinName("", t));
    setError(null);
    setStatus(null);
    setJobId(null);
    setAutoStartAllowed(true);
    statusReceivedAtRef.current = 0;
    // Reset progress floors so the next report doesn't flash the prior 100%/Complete
    // before the new job's first poll lands.
    maxPctRef.current = 0;
    maxStepRef.current = 0;
  };

   
  useEffect(() => {
    // Don't auto-retry after a failed start — otherwise startNewJob (which resets
    // status to null) re-fires in a loop and the user never reaches the stable
    // Error/Retry screen. The Retry button drives the manual restart instead.
    if (autoStartAllowed && !jobId && ticker && !isStarting && status?.status !== "error") startNewJob();
  }, [autoStartAllowed, jobId, ticker, isStarting, companyName, mode, status]);

  /* ── Poll status ── */
  useEffect(() => {
    if (!jobId) return;
    let dead = false, timer;
    const poll = async () => {
      try {
        const d = await getStatus(jobId);
        if (dead) return;
        statusReceivedAtRef.current = Date.now();
        const authoritativeTicker = sanitizeTicker(d.stock_code || "");
        const resolvedTicker = authoritativeTicker || ticker;
        const resolvedCompanyName = toLatinName(d.company_name || "", resolvedTicker);
        setStatus(d);
        setError(null);
        if (authoritativeTicker) setTicker(authoritativeTicker);
        if (resolvedCompanyName) setCompanyName(resolvedCompanyName);
        if (d.status && ["complete", "warning", "error"].includes(d.status)) {
          if (d.status !== "error" && d.html_file) {
            upsertReportHistory({
              jobId,
              ticker: resolvedTicker,
              companyName: resolvedCompanyName || resolvedTicker,
              html: buildBareDownloadUrl(d.html_file),
              pdf: d.pdf_file ? buildBareDownloadUrl(d.pdf_file) : null,
              html_file: d.html_file,
              pdf_file: d.pdf_file || null,
              finishedAt: d.finished_at || new Date().toISOString(),
              sources: d.sources || [],
              status: d.status,
              warning: d.status === "warning" ? (d.error || d.message || "Report completed with a warning") : null,
            });
          }
          return;
        }
        timer = setTimeout(poll, 1200);
      } catch (err) {
        if (dead) return;
        if (err.status === 404) {
          // Job gone from server memory (evicted past the JOBS cap, or a server
          // restart). The finished report file still exists on disk and is saved
          // in history — restore it (the /download view is file-based + beta-gated)
          // instead of silently regenerating (which would waste API + lose the
          // user's instant view of a report they already made).
          const prev = findReportHistory(jobId);
          if (prev?.html_file) {
            const restoredWarning = prev.status === "warning" || Boolean(prev.warning);
            setTicker(sanitizeTicker(prev.ticker));
            setCompanyName(toLatinName(prev.companyName, prev.ticker));
            setStatus({
              status: restoredWarning ? "warning" : "complete",
              html_file: prev.html_file,
              pdf_file: prev.pdf_file || null,
              company_name: prev.companyName,
              stock_code: prev.ticker,
              error: restoredWarning ? prev.warning : null,
            });
            return;
          }
          // A missing job is terminal until the user explicitly chooses Retry.
          // Never silently launch another paid report from a polling failure.
          setAutoStartAllowed(false);
          removeActiveReport(jobId);
          setStatus({ status: "error", error: "This report is no longer available." });
          return;
        }
        setError(err.message || "Status fetch failed");
        timer = setTimeout(poll, 2500);
      }
    };
    poll();
    return () => { dead = true; if (timer) clearTimeout(timer); };
  }, [jobId, ticker]);

  /* ── Handlers ── */
  const viewerReport = { url: safeSameOriginPath(viewHtml), title: companyName || ticker, jobId };
  const handleView = () => {
    const path = reportViewerPath(viewerReport);
    if (path) navigate(path);
  };
  const handleDownload = () => {
    const url = downloadPdf || downloadHtml;
    if (url) { const a = document.createElement("a"); a.href = url; a.download = ""; a.target = "_blank"; a.rel = "noopener"; a.click(); }
  };
  // The same link and toast as the viewer's Copy link: the #/Viewer page, copied.
  const handleShare = () => { copyReportShareLink(viewerReport, toast); };

  /* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   *  Render
   * ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
  return (
    <div className="h-screen-dvh flex flex-col overflow-hidden bg-[#0e1420] text-[#f4f5f7]">

      {/* ━━ Top progress bar ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      <div className="h-[3px] w-full bg-white/[0.06] shrink-0 relative z-50" role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}>
        {isComplete && !reduceMotion && (
          <motion.div
            initial={{ opacity: 0.4 }}
            animate={{ opacity: 0 }}
            transition={{ duration: 0.6, ease: "easeOut" }}
            className={`absolute inset-0 z-10 ${isWarning ? "bg-amber-400/30" : "bg-emerald-400/30"}`}
          />
        )}
        <motion.div
          className={`h-full ${isWarning ? "bg-amber-500" : isComplete ? "bg-emerald-500" : "bg-[#f4f5f7]"}`}
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          // Snaps on completion (a finished job opened directly would otherwise
          // slide 0 -> 100% across the top during the ready entrance).
          transition={{ duration: reduceMotion || isComplete ? 0 : 0.6, ease: "easeOut" }}
        />
        {isRunning && (
          <motion.div
            className="absolute top-0 h-full w-32 bg-gradient-to-r from-transparent via-white/40 to-transparent"
            animate={{ left: ["-8rem", "100%"] }}
            transition={{ duration: 2, repeat: Infinity, ease: "linear" }}
          />
        )}
      </div>

      {/* ━━ Top bar ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      {/* inert while the mobile drawer is up (audit P-07) — React 18 passes the
          unknown attribute through as a string, so "" = set, undefined = absent. */}
      <header inert={isMobile && sidebarOpen ? "" : undefined} className="shrink-0 h-12 sm:h-14 border-b border-white/[0.12] bg-[#0e1420]/90 backdrop-blur-md flex items-center px-3 sm:px-4 gap-2 sm:gap-3 z-40">
        <Link to="/Reports" state={{ openContent: true }} aria-label="Back to Reports" className="flex items-center gap-1.5 text-white/50 hover:text-white/80 transition-colors text-sm shrink-0">
          <ArrowLeft className="w-4 h-4" />
          <span className="hidden sm:inline">Back</span>
        </Link>

        <div className="h-5 w-px bg-white/[0.1] shrink-0" />

        <div className="flex items-center gap-2.5 min-w-0">
          <div className="w-8 h-8 rounded-lg bg-white/[0.05] border border-white/[0.12] flex items-center justify-center shrink-0">
            <Building2 className="w-4 h-4 text-white/50" />
          </div>
          <div className="min-w-0">
            <p className="text-[#f4f5f7] font-medium text-sm truncate leading-tight" title={headerName || undefined}>
              {headerName || (noTarget ? "No company selected" : "Loading...")}
            </p>
            <p className="text-white/50 text-xs leading-tight">
              {headerName !== ticker && <span className="text-[#f4f5f7] font-mono">{ticker}</span>}
              {queue.length > 1 && <span className="ml-1.5 text-white/40">batch {queueIdx + 1}/{queue.length}</span>}
              {status?.financials_source && <span className="ml-1.5 text-white/40">via {status.financials_source}</span>}
            </p>
          </div>
        </div>

        <div className="flex-1" />

        {/* Live stats — hidden on complete (shown in completion card instead) */}
        {isRunning && (
          <div className="hidden md:flex items-center gap-4 text-xs text-white/50">
            {status?.source_count > 0 && <span>Sources: <span className="text-[#f4f5f7] font-mono">{status.source_count}</span></span>}
            {status?.edinet_count > 0 && <span>SEC filings: <span className="text-[#f4f5f7] font-mono">{status.edinet_count}</span></span>}
            {status?.financial_rows > 0 && <span>Fin. rows: <span className="text-[#f4f5f7] font-mono">{status.financial_rows}</span></span>}
          </div>
        )}

        <div className="hidden sm:flex items-center gap-3 text-xs font-mono shrink-0">
          <span className="text-white/50">{fmtTime(elapsed)}</span>
          {isRunning && !isQueued && eta != null && (
            <span className="text-white/80">Est. remaining ~{fmtTime(eta)}</span>
          )}
          <span className={`font-semibold ${isWarning ? "text-amber-400" : isComplete ? "text-emerald-400" : isError ? "text-red-400" : "text-[#f4f5f7]"}`}>
            {Math.round(pct)}%
          </span>
        </div>
      </header>

      {/* ━━ Main layout ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      <div className="flex-1 flex overflow-hidden">

        {/* On mobile the open sidebar overlays the content (with a backdrop) instead
            of pushing it into a sliver. */}
        {isMobile && sidebarOpen && (
          <div
            onClick={() => setSidebarOpen(false)}
            className="fixed inset-0 z-30 bg-black/40"
            aria-hidden="true"
          />
        )}

        {/* ── Sidebar (auto-collapses on complete) ────── */}
        <AnimatePresence initial={false}>
          {sidebarOpen && (
            <motion.aside
              initial={{ width: 0, opacity: 0 }}
              animate={{ width: 260, opacity: 1 }}
              exit={{ width: 0, opacity: 0 }}
              // The auto-collapse on completion must finish before the ready state
              // mounts (stateExit = 0.15 s), or the centred ready block slides
              // sideways while the main column widens. Instant with reduced motion.
              transition={{ duration: reduceMotion ? 0 : isComplete ? 0.15 : 0.3, ease }}
              // Mobile overlay = modal semantics (audit P-07): name it, mark
              // it modal, and let Escape dismiss it like the backdrop click.
              role={isMobile ? "dialog" : undefined}
              aria-modal={isMobile ? "true" : undefined}
              aria-label={isMobile ? "Report pipeline sidebar" : undefined}
              ref={sidebarRef}
              tabIndex={-1}
              onKeyDown={isMobile ? (e => { if (e.key === "Escape") setSidebarOpen(false); }) : undefined}
              className={`shrink-0 border-r border-white/[0.12] bg-[#0e1420] overflow-hidden flex flex-col ${isMobile ? "fixed inset-y-0 left-0 z-40 shadow-2xl" : ""}`}
              style={{ maxWidth: "85vw" }}
            >
              <div className="flex-1 overflow-y-auto p-4 space-y-6" style={{ width: "min(260px, 70vw)" }}>
                {/* Pipeline steps */}
                <div>
                  <h3 className="text-[11px] font-semibold uppercase tracking-widest text-white/50 mb-3 px-1">Pipeline</h3>
                  <div className="space-y-1">
                    {PIPELINE.map((p, i) => {
                      const Icon = p.icon;
                      const done = i < stepIdx || isComplete;
                      // Nothing runs without a company or after a failure: no step is
                      // "LIVE" or spinning then; the step the job failed in is marked.
                      const failed = !noTarget && isError && !isComplete && i === stepIdx;
                      const active = !noTarget && !isError && i === stepIdx && !isComplete && !isQueued;
                      return (
                        <motion.div
                          key={p.key}
                          initial={{ opacity: 0, x: -12 }}
                          animate={{ opacity: done || active || failed ? 1 : 0.55, x: 0 }}
                          transition={{ delay: i * 0.03 }}
                          className={`flex items-center gap-2.5 px-3 py-2 rounded-lg transition-all duration-300 ${
                            active ? "bg-white/[0.06] border border-white/20" : failed ? "bg-red-500/[0.06] border border-red-400/30" : "border border-transparent"
                          }`}
                          data-step-state={done ? "done" : failed ? "failed" : active ? "live" : "waiting"}
                        >
                          {failed ? (
                            <div className="w-5 h-5 rounded-full bg-red-500/15 flex items-center justify-center shrink-0" aria-hidden="true">
                              <X className="w-3 h-3 text-red-400" />
                            </div>
                          ) : done ? (
                            <motion.div initial={{ scale: 0 }} animate={{ scale: 1 }} className="w-5 h-5 rounded-full bg-emerald-500/15 flex items-center justify-center shrink-0">
                              <Check className="w-3 h-3 text-emerald-400" />
                            </motion.div>
                          ) : active ? (
                            <motion.div animate={{ rotate: 360 }} transition={{ duration: 1.2, repeat: Infinity, ease: "linear" }} className="w-5 h-5 rounded-full bg-white/10 flex items-center justify-center shrink-0">
                              <Loader2 className="w-3 h-3 text-[#f4f5f7]" />
                            </motion.div>
                          ) : (
                            <div className="w-5 h-5 rounded-full bg-white/[0.06] flex items-center justify-center shrink-0">
                              <Icon className="w-3 h-3 text-white/50" />
                            </div>
                          )}
                          <span className={`text-xs font-medium ${active || done ? "text-[#f4f5f7]" : failed ? "text-red-300" : "text-[#f4f5f7]/60"}`}>
                            {p.label}
                          </span>
                          {failed && <span className="ml-auto text-[10px] font-semibold text-red-400">Failed</span>}
                          {active && (
                            <motion.span animate={{ opacity: [1, 0.4, 1] }} transition={{ duration: 1.5, repeat: Infinity }} className="ml-auto text-[10px] font-semibold text-white/70">LIVE</motion.span>
                          )}
                          {done && <Check className="ml-auto w-3 h-3 text-emerald-400/40" />}
                        </motion.div>
                      );
                    })}
                  </div>
                </div>

                {/* Data health */}
                <div>
                  <h3 className="text-[11px] font-semibold uppercase tracking-widest text-white/50 mb-3 px-1">Data</h3>
                  <div className="space-y-2 px-1">
                    {[
                      { l: "Sources", v: status?.source_count },
                      { l: "SEC filings", v: status?.edinet_count },
                      { l: "Scanned", v: status?.edinet_scanned && status?.edinet_total ? `${status.edinet_scanned}/${status.edinet_total}` : null },
                      { l: "Financial rows", v: status?.financial_rows },
                      { l: "Price rows", v: status?.price_rows },
                    ].filter((x) => x.v != null && x.v !== 0).map((s) => (
                      <div key={s.l} className="flex justify-between items-center">
                        <span className="text-[11px] text-white/50">{s.l}</span>
                        <span className="text-[11px] font-mono text-[#f4f5f7]">{s.v}</span>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Timing */}
                <div>
                  <h3 className="text-[11px] font-semibold uppercase tracking-widest text-white/50 mb-3 px-1">Timing</h3>
                  <div className="space-y-2 px-1">
                    <div className="flex justify-between items-center">
                      <span className="text-[11px] text-white/50">Elapsed</span>
                      <span className="text-[11px] font-mono text-[#f4f5f7]">{fmtTime(elapsed)}</span>
                    </div>
                    {isRunning && !isQueued && eta != null && (
                      <div className="flex justify-between items-center">
                        <span className="text-[11px] text-white/50">Est. remaining</span>
                        <span className="text-[11px] font-mono text-[#f4f5f7]">~{fmtTime(eta)}</span>
                      </div>
                    )}
                    <div className="flex justify-between items-center">
                      <span className="text-[11px] text-white/50">Progress</span>
                      <span className="text-[11px] font-mono text-[#f4f5f7]">{Math.round(pct)}%</span>
                    </div>
                  </div>
                </div>
              </div>

              {/* Sidebar footer */}
              <div className="p-3 border-t border-white/[0.12]">
                <button onClick={() => setSidebarOpen(false)} className="w-full flex items-center justify-center gap-2 py-2 rounded-lg text-white/50 hover:text-white/70 hover:bg-white/[0.05] transition-colors text-xs">
                  <PanelLeftClose className="w-3.5 h-3.5" />Collapse
                </button>
              </div>
            </motion.aside>
          )}
        </AnimatePresence>

        {/* Sidebar toggle (when collapsed + running) */}
        {!sidebarOpen && isRunning && (
          <motion.button
            initial={{ opacity: 0, x: -10 }}
            animate={{ opacity: 1, x: 0 }}
            onClick={() => setSidebarOpen(true)}
            aria-label="Open pipeline sidebar"
            className="absolute left-2 top-[76px] z-30 w-8 h-8 rounded-lg bg-white/[0.05] border border-white/[0.12] flex items-center justify-center text-white/50 hover:text-white/70 hover:bg-white/[0.08] transition-colors"
          >
            <PanelLeftOpen className="w-4 h-4" />
          </motion.button>
        )}

        {/* ── Main content area ────────────────────────── */}
        <main inert={isMobile && sidebarOpen ? "" : undefined} className="flex-1 flex flex-col overflow-hidden relative">
          {/* Ambient glow */}
          <div className="absolute inset-0 pointer-events-none z-0">
            <motion.div
              animate={{ background: isComplete ? "radial-gradient(circle at 40% 30%, rgba(16,185,129,0.05) 0%, transparent 60%)" : "radial-gradient(circle at 50% 40%, rgba(255,255,255,0.03) 0%, transparent 60%)" }}
              transition={{ duration: 2 }}
              className="absolute inset-0"
            />
            {isComplete && (
              <motion.div
                initial={readyEnter}
                animate={{ opacity: 1 }}
                transition={readyFade}
                className="absolute inset-0"
                style={{ background: "radial-gradient(circle at 60% 70%, rgba(59,130,246,0.03) 0%, transparent 50%)" }}
              />
            )}
          </div>

          {/* Scrollable content */}
          <div ref={contentRef} className="flex-1 overflow-y-auto relative z-10">
            <AnimatePresence mode="wait">

              {/* ━━ EMPTY STATE (no company selected) ━━━━━━ */}
              {noTarget && (
                <motion.div
                  key="empty"
                  initial={{ opacity: 0, y: 16 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.5 }}
                  className="flex flex-col items-center justify-center min-h-full py-32 px-6 text-center"
                >
                  <div className="w-16 h-16 rounded-[20px] bg-white/[0.05] border border-white/[0.12] flex items-center justify-center mb-6">
                    <FileText className="w-7 h-7 text-white/40" />
                  </div>
                  <h2 className="text-xl font-semibold text-[#f4f5f7] mb-2 tracking-tight">No company selected</h2>
                  <p className="text-white/50 text-sm mb-8 max-w-sm">
                    Pick a company on the Reports page to generate a research report.
                  </p>
                  <Link
                    to="/Reports"
                    state={{ openContent: true }}
                    className="inline-flex items-center gap-2 px-6 py-3 rounded-2xl bg-[#f4f5f7] hover:bg-[#dfe3ea] text-[#0e1420] font-medium text-sm transition-colors"
                  >
                    <ArrowLeft className="w-4 h-4" /> Back to Reports
                  </Link>
                </motion.div>
              )}

              {/* ━━ RUNNING STATE ━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
              {isRunning && (
                <motion.div
                  key="running"
                  initial={readyEnter}
                  animate={{ opacity: 1 }}
                  exit={stateExit}
                  transition={readyFade}
                  className="flex flex-col items-center justify-center min-h-full py-32 px-6"
                >
                  {/* Animated orb */}
                  <div className="relative mb-8">
                    <motion.div
                      animate={{ scale: [1, 1.15, 1], opacity: [0.5, 1, 0.5] }}
                      transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
                      className="w-20 h-20 rounded-full bg-gradient-to-br from-white/15 to-white/5 flex items-center justify-center"
                    >
                      <motion.div
                        animate={{ rotate: 360 }}
                        transition={{ duration: 8, repeat: Infinity, ease: "linear" }}
                        className="w-12 h-12 rounded-full border-2 border-white/20 border-t-[#f4f5f7]"
                      />
                    </motion.div>
                    <motion.div
                      animate={{ scale: [1, 1.3, 1], opacity: [0.3, 0, 0.3] }}
                      transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
                      className="absolute inset-0 rounded-full border border-white/15"
                    />
                  </div>

                  <AnimatePresence mode="wait">
                    <motion.p
                      key={step + stageMsg}
                      initial={{ opacity: 0, y: 8 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -8 }}
                      transition={{ duration: 0.3 }}
                      className="text-white/60 text-base text-center"
                    >
                      {stageMsg}
                    </motion.p>
                  </AnimatePresence>

                  <motion.p
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ delay: 0.5 }}
                    className="text-white/50 text-sm mt-3"
                  >
                    {isQueued
                      ? "Queued — waiting for a worker"
                      : `${step} — ${Math.round(pct)}% reported progress`}
                  </motion.p>

                  {step === "Data Fetch" && progressView.filingsFound != null && (
                    <p className="text-white/50 text-sm mt-2">
                      {progressView.filingsFound} SEC filing{progressView.filingsFound === 1 ? "" : "s"} found so far
                    </p>
                  )}
                  {!isQueued && eta == null && (
                    <p className="text-white/50 text-xs mt-2">Remaining time is uncertain; status updates will appear here.</p>
                  )}

                  {error && (
                    <p className="text-red-400 text-sm mt-4 bg-red-500/10 border border-red-400/30 rounded-lg px-4 py-2">{error}</p>
                  )}
                </motion.div>
              )}

              {/* ━━ COMPLETE STATE ━━━━━━━━━━━━━━━━━━━━━━━━━ */}
              {isComplete && (
                <motion.div
                  key="complete"
                  initial={readyEnter}
                  animate={{ opacity: 1 }}
                  transition={readyFade}
                  className="flex flex-col items-center min-h-full"
                >
                  {/* Spacer */}
                  <div className="flex-1 min-h-[8vh] max-h-[15vh]" />

                  {/* Success icon — clean, minimal, no entrance of its own */}
                  <div className="mb-6">
                    <div className={`w-16 h-16 rounded-[20px] flex items-center justify-center ${isWarning ? "bg-gradient-to-b from-amber-500/15 to-amber-500/5 border border-amber-400/30 shadow-[0_8px_40px_rgba(245,158,11,0.12)]" : "bg-gradient-to-b from-emerald-500/15 to-emerald-500/5 border border-emerald-400/25 shadow-[0_8px_40px_rgba(16,185,129,0.12)]"}`}>
                      {isWarning
                        ? <span className="text-2xl font-semibold text-amber-400" aria-hidden="true">!</span>
                        : <Check className="w-8 h-8 text-emerald-400" strokeWidth={2.5} />}
                    </div>
                  </div>

                  {/* Title */}
                  <h1 className="text-2xl sm:text-3xl font-semibold text-[#f4f5f7] tracking-tight mb-2">
                    {isWarning ? "Report ready with a warning" : "Your report is ready"}
                  </h1>

                  <p className="text-white/50 text-sm mb-8">
                    {companyName || ticker} — {fmtTime(elapsed)} — {status?.source_count || 0} sources
                  </p>

                  {isWarning && (
                    <div
                      role="alert"
                      className="mx-6 mb-6 max-w-xl rounded-xl border border-amber-400/30 bg-amber-500/10 px-4 py-3 text-center text-sm text-amber-300"
                    >
                      <span className="font-semibold">
                        {downloadHtml ? "The report is ready, with a note." : "The report completed with a warning."}
                      </span>{" "}
                      {warningMessage}
                    </div>
                  )}

                  {/* ── Primary CTA ── */}
                  <div className="flex flex-col items-center gap-4 mb-10">
                    {viewHtml && (
                      <motion.button
                        whileHover={{ scale: 1.02, y: -1 }}
                        whileTap={{ scale: 0.98 }}
                        onClick={handleView}
                        className="group inline-flex items-center gap-3 px-8 py-3.5 rounded-2xl bg-[#f4f5f7] text-[#0e1420] font-medium text-[15px] shadow-[0_4px_24px_rgba(0,0,0,0.12)] hover:shadow-[0_8px_32px_rgba(0,0,0,0.18)] transition-shadow duration-300"
                      >
                        <ExternalLink className="w-[18px] h-[18px] opacity-60 group-hover:opacity-100 transition-opacity" />
                        View Report
                      </motion.button>
                    )}

                    {/* Secondary actions — minimal icon row */}
                    <div className="flex flex-wrap items-center justify-center gap-1">
                      {(downloadPdf || downloadHtml) && (
                        <button onClick={handleDownload} className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-white/50 hover:text-[#f4f5f7] hover:bg-white/[0.06] transition-all duration-200 text-[13px]">
                          <Download className="w-3.5 h-3.5" />
                          <span>{downloadPdf ? "Download PDF" : isWarning ? "Download HTML" : "Download"}</span>
                        </button>
                      )}
                      <button onClick={handleShare} className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-white/50 hover:text-[#f4f5f7] hover:bg-white/[0.06] transition-all duration-200 text-[13px]">
                        <Share2 className="w-3.5 h-3.5" />
                        <span>Share</span>
                      </button>
                      <button onClick={() => setShowSources(true)} className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-white/50 hover:text-[#f4f5f7] hover:bg-white/[0.06] transition-all duration-200 text-[13px]">
                        <BookOpen className="w-3.5 h-3.5" />
                        <span>Sources</span>
                      </button>
                    </div>
                  </div>

                  {/* ── Report preview card ──
                      Fades in with the block only: no slide, scale or light sweep
                      (the old sweep also overflowed the scroller sideways). Its
                      height is fixed by the iframe style from the first frame. */}
                  {viewHtml && (
                    <div className="w-full max-w-4xl mx-auto px-6">
                      {/* Report frame — click to open viewer */}
                      <button onClick={handleView} className="block w-full text-left group cursor-pointer">
                        <div className="rounded-2xl overflow-hidden bg-white shadow-[0_2px_20px_rgba(0,0,0,0.06),0_12px_48px_rgba(0,0,0,0.06)] border border-black/[0.06] group-hover:shadow-[0_4px_24px_rgba(0,0,0,0.08),0_16px_56px_rgba(0,0,0,0.08)] transition-shadow duration-500 relative">
                          {/* Hover overlay */}
                          <div className="absolute inset-0 z-20 bg-black/0 group-hover:bg-black/[0.02] transition-colors duration-300 flex items-center justify-center rounded-2xl">
                            {/* Hint fades in while the card is hovered or focused; it never moves or scales. */}
                            <div className="opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100 transition-opacity duration-300 bg-white/95 backdrop-blur-sm rounded-xl px-5 py-2.5 shadow-lg border border-black/[0.06] flex items-center gap-2 text-sm font-medium text-[#0a0a0a]">
                              <ExternalLink className="w-4 h-4" />
                              Open Full Screen
                            </div>
                          </div>
                          {/* Loading skeleton — hidden once the iframe fires onLoad */}
                          {!previewLoaded && !previewError && (
                            <div className="absolute inset-0 z-10 bg-white flex items-center justify-center pointer-events-none">
                              <Loader2 className="w-6 h-6 text-gray-300 animate-spin" />
                            </div>
                          )}
                          {/* Error fallback — preview failed to load */}
                          {previewError && (
                            <div className="absolute inset-0 z-10 bg-white flex flex-col items-center justify-center gap-2 px-6 text-center pointer-events-none">
                              <FileText className="w-7 h-7 text-gray-300" />
                              <p className="text-gray-400 text-sm">Preview unavailable — open the full report to view it.</p>
                            </div>
                          )}
                          <iframe
                            src={viewHtml}
                            title={`${companyName || ticker} Research Report`}
                            className="w-full bg-white pointer-events-none"
                            style={{ height: "clamp(40vh, 60vh, 70vh)", border: "none" }}
                            tabIndex={-1}
                            loading="lazy"
                            onLoad={(event) => {
                              // A missing file answers 404 JSON: show the fallback, not the raw JSON.
                              let contentType = "";
                              try { contentType = String(event.currentTarget.contentDocument?.contentType || ""); } catch { contentType = ""; }
                              if (contentType && contentType !== "text/html") setPreviewError(true);
                              else setPreviewLoaded(true);
                            }}
                            onError={() => setPreviewError(true)}
                          />
                        </div>
                      </button>
                    </div>
                  )}

                  {/* Bottom actions */}
                  <div className="flex flex-wrap items-center justify-center gap-3 py-10">
                    {hasNextInQueue && (
                      <button
                        onClick={() => startQueueItem(queueIdx + 1)}
                        disabled={isStarting}
                        className="flex items-center gap-2 px-5 py-2.5 rounded-2xl bg-[#f4f5f7] hover:bg-[#dfe3ea] text-[#0e1420] font-medium text-[13px] transition-colors disabled:opacity-50"
                      >
                        Next report ({queueIdx + 2} of {queue.length}): {queue[queueIdx + 1]}
                        <ExternalLink className="w-3.5 h-3.5 opacity-60" />
                      </button>
                    )}
                    {/* "New report" picks another company on Reports. A finished report
                        is re-run only when it came with a warning ("Run again"). */}
                    <Link
                      to="/Reports"
                      state={{ openContent: true }}
                      className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-white/40 hover:text-white/60 hover:bg-white/[0.05] transition-all text-[13px]"
                    >
                      <Plus className="w-3.5 h-3.5" />
                      New report
                    </Link>
                    {isWarning && (
                      <button
                        onClick={() => startNewJob()}
                        disabled={isStarting}
                        className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-white/40 hover:text-white/60 hover:bg-white/[0.05] transition-all text-[13px] disabled:opacity-40"
                      >
                        <RotateCcw className="w-3.5 h-3.5" />
                        Run again
                      </button>
                    )}
                    <Link
                      to="/Home"
                      className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-white/40 hover:text-white/60 hover:bg-white/[0.05] transition-all text-[13px]"
                    >
                      <ArrowLeft className="w-3.5 h-3.5" />
                      Home
                    </Link>
                  </div>
                </motion.div>
              )}

              {/* ━━ ERROR STATE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
              {!isComplete && isError && (
                <motion.div
                  key="error"
                  initial={readyEnter}
                  animate={{ opacity: 1 }}
                  exit={stateExit}
                  transition={readyFade}
                  className="flex flex-col items-center justify-center min-h-full py-24 px-6"
                >
                  <div className="w-16 h-16 rounded-[20px] bg-gradient-to-b from-red-500/15 to-red-500/5 border border-red-400/25 flex items-center justify-center mb-6 shadow-[0_8px_40px_rgba(239,68,68,0.08)]">
                    <span className="text-2xl font-light text-red-400">!</span>
                  </div>
                  <h2 className="text-xl font-semibold text-[#f4f5f7] mb-2 tracking-tight">Generation Failed</h2>
                  <p className="text-white/60 text-sm mb-1 text-center max-w-md">{status?.error || "An unexpected error occurred."}</p>
                  {error && error !== status?.error && <p className="text-red-400 text-xs mb-1">{error}</p>}
                  <p className="text-white/40 text-xs mb-8">Check that the ticker is valid, or try a different company.</p>
                  <div className="flex gap-3">
                    <motion.button
                      whileHover={{ scale: 1.02 }}
                      whileTap={{ scale: 0.98 }}
                      onClick={() => startNewJob()}
                      disabled={isStarting}
                      className="inline-flex items-center gap-2 px-6 py-3 rounded-2xl bg-[#f4f5f7] hover:bg-[#dfe3ea] text-[#0e1420] font-medium text-sm disabled:opacity-50 transition-colors"
                    >
                      <RotateCcw className="w-4 h-4" />Retry
                    </motion.button>
                    <Link
                      to="/Reports"
                      state={{ openContent: true }}
                      className="inline-flex items-center gap-2 px-5 py-3 rounded-2xl border border-white/[0.14] text-white/60 hover:text-[#f4f5f7] hover:border-white/[0.18] transition-colors text-sm"
                    >
                      Try different company
                    </Link>
                  </div>
                </motion.div>
              )}

            </AnimatePresence>
          </div>

          {/* ── Bottom status bar (while running) ── */}
          {isRunning && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="shrink-0 border-t border-white/[0.12] bg-[#0e1420]/95 backdrop-blur-sm px-6 py-3 flex items-center justify-between z-20"
            >
              <div className="flex items-center gap-3 text-xs text-white/50 min-w-0 flex-1">
                <Loader2 className="w-3.5 h-3.5 text-[#f4f5f7] animate-spin shrink-0" />
                <span className="text-white/60 truncate">{status?.message || stageMsg}</span>
              </div>
              <div className="flex items-center gap-4 text-xs font-mono shrink-0 pl-3">
                <span className="text-white/50">{fmtTime(elapsed)}</span>
                <span className="text-[#f4f5f7]">{Math.round(pct)}%</span>
              </div>
            </motion.div>
          )}
        </main>
      </div>

      <SourcesModal
        isOpen={showSources}
        onClose={() => setShowSources(false)}
        sources={status?.sources || []}
        companyName={companyName || ticker}
      />
    </div>
  );
}

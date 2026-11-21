import React, { useMemo, useState, useRef, useEffect, useCallback } from "react";
import IndagoLoader from "@/components/IndagoLoader";
import { useLocation, useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import {
  ArrowLeft, BookOpen, Globe, FileText,
  ExternalLink, Search, Database, X,
  Copy, Check, ZoomIn, ZoomOut,
  Maximize2, Minimize2, Printer, Share2, PenLine,
  Keyboard, Trash2, Download, Clock,
  Terminal, AlertCircle,
} from "lucide-react";
import { toast } from "@/components/ui/use-toast";
import { getStatus } from "@/api/backend";
import { normalizeJobId, normalizeReportEntry, readReportHistory } from "@/lib/reportStorage";
import { createBrowserStorage } from "@/lib/browserStorage";
import { extractReportFileName, safeExternalUrl, safeReportUrl, safeSameOriginPath } from "@/lib/safeUrl";
import { copyReportShareLink } from "@/lib/reportShareLink";


/* ── Helpers ──────────────────────────────────────────────── */
function extractFileName(url) {
  return extractReportFileName(url);
}

/** The report entry if the Viewer URL's file is one of its own artifacts. */
function entryMatchingFile(entry, file) {
  if (!entry) return null;
  if (!file) return entry;
  const exactFiles = new Set([
    entry.html_file,
    entry.pdf_file,
    extractFileName(entry.html),
    extractFileName(entry.pdf),
  ].filter(Boolean));
  return exactFiles.has(file) ? entry : null;
}

function findReportInHistory(jobId, url) {
  const history = readReportHistory();
  const requestedJobId = jobId ? normalizeJobId(jobId) : null;
  const file = extractFileName(url);
  if (jobId && !requestedJobId) return null;

  if (requestedJobId) {
    return entryMatchingFile(history.find((entry) => entry.jobId === requestedJobId), file);
  }

  if (!file) return null;
  return history.find((entry) => [
    entry.html_file,
    entry.pdf_file,
    extractFileName(entry.html),
    extractFileName(entry.pdf),
  ].includes(file)) || null;
}

/**
 * A shared link opened in a browser without this report in its history: the
 * owner-scoped /status/{jobId} answer rebuilds the same entry the history would
 * hold (ticker, PDF, sources, finish time), or null when the job is not this
 * account's, not finished, or not the report the URL names.
 */
export function reportEntryFromStatus(status, jobId, url) {
  const id = normalizeJobId(jobId);
  if (!id || normalizeJobId(status?.job_id) !== id) return null;
  if (status.status !== "complete" && status.status !== "warning") return null;
  const entry = normalizeReportEntry({
    jobId: id,
    ticker: status.stock_code,
    companyName: status.company_name,
    html_file: status.html_file,
    pdf_file: status.pdf_file,
    sources: status.sources,
    finishedAt: status.finished_at || null,
    status: status.status,
  });
  return entryMatchingFile(entry, extractFileName(url));
}

function getViewerIdentity(searchString) {
  const params = new URLSearchParams(searchString);
  const rawJobId = params.get("jobId");
  const jobId = normalizeJobId(rawJobId);
  const rawUrl = safeReportUrl(params.get("url"));
  const fileName = extractFileName(rawUrl);
  if (fileName) return `report:${jobId || "legacy"}:${fileName}`;
  if (rawJobId) return `invalid-job:${rawJobId}`;

  const report = findReportInHistory(null, rawUrl);
  const ticker = String(report?.ticker || "").trim();
  if (ticker) return `company:${ticker}`;

  const title = (params.get("title") || "Report").trim();
  return `title:${title}`;
}

const FOCUSABLE_SELECTOR = "button:not([disabled]), a[href], input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex='-1'])";
// The report template switches to its phone layout at or below this width, so
// fit-to-width scaling only applies above it.
const PHONE_LAYOUT_MAX_WIDTH = 640;

/** The frame's layout width at a zoom: the pane width divided by the zoom, but
 *  never narrower than the sheet's own width once that is known. */
export function zoomedFrameWidth(frameZoom, sheetMinWidth = 0) {
  const share = `${100 / frameZoom}%`;
  return sheetMinWidth > 0 ? `max(${share}, ${Math.ceil(sheetMinWidth)}px)` : share;
}

/* ── Reading desk (light theme of this page only) ───────────
 * The report is a white printed sheet, so the viewer around it is a light
 * desk rather than the app's navy. The palette, used as Tailwind arbitrary
 * values below:
 *   canvas   #eceef2   behind the sheet          ink        #0e1420  text, icons
 *   surface  #ffffff   top bar, panel, cards     secondary  #5b6472  quieter text
 *   hairline #dfe3e8   borders, outlines         mono meta  #7b8494  dates
 *   card     #e6e9ee   source-card border        hover      #f1f3f6  fills, tab track
 *   active   #e9edf5   active panel button       status bar #f6f7f9
 *   SEC chip #8a5a00 on #fbf1d9                  WEB chip   #1d4ed8 on #e3ecff
 * The sheet's own canvas lives in the report document; on screens wider than
 * the report's phone layout the viewer lays the desk colour under it and
 * gives the sheet a hairline and a soft shadow (screen only, print untouched). */
const DESK_FRAME_STYLE_ID = "viewer-desk";
const DESK_FRAME_CSS = `@media screen and (min-width: ${PHONE_LAYOUT_MAX_WIDTH + 1}px) {
  html, body { background: #eceef2 !important; }
  .dashboard { border-color: #d9dde3 !important; box-shadow: 0 1px 2px rgba(14,20,32,.05), 0 6px 24px rgba(14,20,32,.07); }
}`;
function dressReportFrame(frame) {
  try {
    const doc = frame?.contentDocument;
    if (!doc?.head || doc.getElementById(DESK_FRAME_STYLE_ID)) return;
    const style = doc.createElement("style");
    style.id = DESK_FRAME_STYLE_ID;
    style.textContent = DESK_FRAME_CSS;
    doc.head.appendChild(style);
  } catch { /* A frame that is not same-origin keeps its own canvas. */ }
}
// Toasts raised by this page match the desk (the global toast is navy).
const DESK_TOAST = "border-[#dfe3e8] bg-white text-[#0e1420] shadow-[0_8px_28px_rgba(14,20,32,0.12)] [&_[toast-close]]:text-[#5b6472] [&_[toast-close]:hover]:text-[#0e1420]";
const deskToast = (options) => toast({ ...options, className: DESK_TOAST });

function trapFocus(event, container) {
  if (event.key !== "Tab" || !container) return;
  const focusable = [...container.querySelectorAll(FOCUSABLE_SELECTOR)]
    .filter((element) => !element.hidden && element.getAttribute("aria-hidden") !== "true");
  if (!focusable.length) { event.preventDefault(); container.focus(); return; }
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && (document.activeElement === first || document.activeElement === container)) {
    event.preventDefault(); last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault(); first.focus();
  }
}

/* ── Note templates ──────────────────────────────────────── */
const NOTE_TEMPLATES = [
  { label: "Thesis", text: "Investment Thesis:\n\u2022 " },
  { label: "Risks", text: "Key Risks:\n\u2022 " },
  { label: "Questions", text: "Follow-up Questions:\n\u2022 " },
  { label: "Catalysts", text: "Catalysts & Timeline:\n\u2022 " },
  { label: "Action", text: "Action Items:\n\u2022 " },
];

/* ── Keyboard shortcuts ─────────────────────────────────── */
const SHORTCUTS = [
  { keys: ["1"], desc: "Sources" },
  { keys: ["2"], desc: "Notes" },
  { keys: ["Esc"], desc: "Close panel" },
  { keys: ["+"], desc: "Zoom in" },
  { keys: ["-"], desc: "Zoom out" },
  { keys: ["0"], desc: "Reset zoom" },
  { keys: ["F"], desc: "Fullscreen" },
  { keys: ["P"], desc: "Print report" },
  { keys: ["?"], desc: "This help" },
];


/* ── Source card ─────────────────────────────────────────── */
function SourceCard({ source, index }) {
  const sourceUrl = safeExternalUrl(source.url);
  let hostname = "";
  try { hostname = new URL(sourceUrl).hostname.replace("www.", ""); } catch { /* An invalid source URL leaves the optional hostname empty. */ }
  const isEdinet = source.type === "edinet";

  return (
    <motion.a
      href={sourceUrl || undefined}
      target={sourceUrl ? "_blank" : undefined}
      rel="noreferrer"
      onClick={sourceUrl ? undefined : (e) => e.preventDefault()}
      aria-disabled={sourceUrl ? undefined : "true"}
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: Math.min(index * 0.015, 0.4), duration: 0.3 }}
      className="group flex gap-3 p-3 rounded-xl bg-white border border-[#e6e9ee] hover:bg-[#f8f9fb] hover:border-[#d5dae1] transition-all duration-200"
    >
      <div className="shrink-0 mt-0.5">
        <span className={`inline-flex items-center justify-center w-6 h-6 rounded-lg text-[10px] font-bold tabular-nums ${
          isEdinet
            ? "bg-[#fdf7ea] text-[#8a5a00] ring-1 ring-[#f2e3bf]"
            : "bg-[#f1f5ff] text-[#1d4ed8] ring-1 ring-[#d7e3ff]"
        }`}>
          {source.id || index + 1}
        </span>
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-0.5">
          <span className={`text-[9px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded ${
            isEdinet ? "bg-[#fbf1d9] text-[#8a5a00]" : "bg-[#e3ecff] text-[#1d4ed8]"
          }`}>
            {isEdinet ? "SEC" : "WEB"}
          </span>
          {hostname && (
            <span className="text-[10px] text-[#7b8494] font-mono truncate">{hostname}</span>
          )}
        </div>
        <p className="text-[12px] text-[#0e1420] font-medium leading-snug line-clamp-1 transition-colors">
          {source.title || hostname || "Untitled"}
        </p>
        {source.snippet && (
          <p className="text-[11px] text-[#5b6472] leading-relaxed line-clamp-2 mt-1">{source.snippet}</p>
        )}
        {source.date && (
          <p className="text-[10px] text-[#7b8494] mt-1 font-mono">{source.date}</p>
        )}
      </div>

      {sourceUrl && <ExternalLink className="w-3 h-3 text-transparent group-hover:text-[#5b6472] transition-colors shrink-0 mt-1" />}
    </motion.a>
  );
}

/* ── Main component ──────────────────────────────────────── */
export default function ReportViewer() {
  const { search } = useLocation();
  const viewerIdentity = useMemo(() => getViewerIdentity(search), [search]);
  return <ReportViewerContent key={viewerIdentity} />;
}

function ReportViewerContent() {
  const [notesStorage] = useState(() => createBrowserStorage());
  const location = useLocation();
  const navigate = useNavigate();

  const search = useMemo(() => new URLSearchParams(location.search), [location.search]);

  const requestedUrl = search.get("url");
  const rawUrl = safeReportUrl(requestedUrl);
  // Defense in depth for legacy/bookmarked Viewer links: source requests are
  // sanitized below, but the SPA location itself must also be replaced so an
  // unsafe value cannot remain in browser history or a copied address.
  useEffect(() => {
    if (!requestedUrl || requestedUrl === rawUrl) return;
    const safeSearch = new URLSearchParams(location.search);
    if (rawUrl) safeSearch.set("url", rawUrl);
    else safeSearch.delete("url");
    navigate(
      { pathname: location.pathname, search: safeSearch.toString() ? `?${safeSearch}` : "" },
      { replace: true, state: location.state },
    );
  }, [requestedUrl, rawUrl, location.pathname, location.search, location.state, navigate]);
  const url = rawUrl;
  const viewUrl = useMemo(() => safeSameOriginPath(url), [url]);
  const requestedJobId = search.get("jobId");
  const normalizedRequestedJobId = normalizeJobId(requestedJobId);
  const isPdf = url && url.toLowerCase().includes(".pdf");

  // Without a valid report file nothing is bound: no stale title, ticker or
  // source counts from the job named in the link.
  const historyReport = useMemo(
    () => (url ? findReportInHistory(requestedJobId, url) : null),
    [requestedJobId, url],
  );
  // Not in this browser's history (a copied link on another browser or
  // device): ask the owner-scoped /status for the same binding before calling
  // it a mismatch. Until it answers, the tools stay unbound.
  const statusBindingKey = url && !historyReport && normalizedRequestedJobId ? `${normalizedRequestedJobId}|${url}` : null;
  const [statusBinding, setStatusBinding] = useState(null);
  useEffect(() => {
    if (!statusBindingKey) return undefined;
    let cancelled = false;
    getStatus(normalizedRequestedJobId)
      .then((status) => reportEntryFromStatus(status, normalizedRequestedJobId, url))
      .catch(() => null)
      .then((entry) => { if (!cancelled) setStatusBinding({ key: statusBindingKey, entry }); });
    return () => { cancelled = true; };
  }, [normalizedRequestedJobId, statusBindingKey, url]);
  const statusEntry = statusBinding?.key === statusBindingKey ? statusBinding : null;
  const bindingPending = Boolean(statusBindingKey && !statusEntry);
  const reportData = historyReport || statusEntry?.entry || null;
  const fileName = useMemo(() => extractFileName(url), [url]);
  const bindingMismatch = Boolean(url && requestedJobId && (!normalizedRequestedJobId || (!reportData && !bindingPending)));
  const jobId = bindingMismatch ? null : bindingPending ? null : (reportData?.jobId || normalizedRequestedJobId);
  // Mismatch keeps the tools unbound (jobId/notesKey stay null) but may still
  // show the URL's own display title (audit P-10) — plain-text render, same
  // trust level as legacy no-jobId links.
  /* ── Report availability ───────────────────── */
  // A deleted or not-owned report answers 404 JSON, which the frame would show
  // raw. An HTML report is requested once, by the frame itself: when it loads,
  // a document that is not HTML (the 404 JSON) turns into the unavailable state
  // (the loader covers the frame until then). A PDF goes into an <object> whose
  // document cannot be read, so for a PDF the status is asked first.
  const [documentCheck, setDocumentCheck] = useState({ url: null, available: true });
  useEffect(() => {
    if (!viewUrl || !isPdf) return undefined;
    const controller = new AbortController();
    fetch(viewUrl, { credentials: "same-origin", cache: "no-store", signal: controller.signal })
      .then((response) => {
        setDocumentCheck({ url: viewUrl, available: response.ok });
        controller.abort();   // only the status was needed; the object loads the document
      })
      .catch(() => {
        if (!controller.signal.aborted) setDocumentCheck({ url: viewUrl, available: true });
      });
    return () => controller.abort();
  }, [viewUrl, isPdf]);
  const documentChecked = Boolean(viewUrl) && (!isPdf || documentCheck.url === viewUrl);
  const reportUnavailable = documentChecked && documentCheck.url === viewUrl && !documentCheck.available;
  const reportReady = documentChecked && !reportUnavailable;
  // No report can be shown: no valid file in the link, or the file is gone.
  const noReport = !url || reportUnavailable;
  const shownReport = noReport ? null : reportData;
  // A large report (several MB of HTML) takes seconds to parse: show the loader over the
  // frame until it has loaded, instead of a blank white pane.
  const [frameLoaded, setFrameLoaded] = useState(false);
  useEffect(() => { setFrameLoaded(false); }, [viewUrl]);
  const handleFrameLoad = (event) => {
    let contentType = "";
    try { contentType = String(event.currentTarget.contentDocument?.contentType || ""); } catch { contentType = ""; }
    if (contentType && contentType !== "text/html") {
      setDocumentCheck({ url: viewUrl, available: false });
      return;
    }
    setFrameLoaded(true);
    measureFit();
  };

  const title = bindingMismatch
    ? (search.get("title") || "Report")
    : reportData?.companyName || search.get("title") || "Report";
  const companyName = noReport ? "" : (shownReport?.companyName || title);
  const sources = useMemo(() => shownReport?.sources || [], [shownReport]);
  const ticker = shownReport?.ticker || "";
  const notesKey = !bindingMismatch && fileName && !bindingPending
    ? `${jobId ? `job:${jobId}:` : ""}file:${fileName}`
    : null;
  const legacyNotesKeys = useMemo(
    () => reportData ? [jobId, fileName].filter(Boolean) : [],
    [fileName, jobId, reportData],
  );

  /* ── Panel state ───────────────────────────── */
  // The panel has two tabs. An older link that asks for another tab (the
  // retired "ai" or "calc", via router state or ?tab=) opens Sources.
  const requestedTab = location.state?.openTab || search.get("tab");
  const initTab = requestedTab ? (requestedTab === "notes" ? "notes" : "sources") : null;
  const [panelOpen, setPanelOpen] = useState(!!initTab);
  // On phones the side panel must take over the full screen rather than squeeze
  // the report into a sliver beside it.
  const [isMobile, setIsMobile] = useState(() => typeof window !== "undefined" && window.innerWidth < 768);
  useEffect(() => {
    const onResize = () => setIsMobile(window.innerWidth < 768);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  const [activeTab, setActiveTab] = useState(initTab || "sources");
  const [sourceFilter, setSourceFilter] = useState("");

  /* ── Viewer state ──────────────────────────── */
  const [zoom, setZoom] = useState(1);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const mobilePanelRef = useRef(null);
  const shortcutsRef = useRef(null);
  const reportFrameRef = useRef(null);
  const mobileReturnFocusRef = useRef(null);
  const shortcutsReturnFocusRef = useRef(null);

  /* ── Fit to width ──────────────────────────── */
  // The report is an A4 sheet (210 mm ≈ 794 px). Between the phone layout and
  // that width (tablets) the sheet would be clipped, so the frame is scaled to
  // the pane's width; the user's zoom multiplies on top. Measured from the
  // same-origin document at its natural scale, so it follows the template.
  const [fitZoom, setFitZoom] = useState(1);
  const fitZoomRef = useRef(1);
  const naturalWidthRef = useRef(0);
  const zoomRef = useRef(zoom);
  zoomRef.current = zoom;
  const measureFit = useCallback(() => {
    const frame = reportFrameRef.current;
    const pane = frame?.parentElement;
    if (!frame || !pane) return;
    const paneWidth = pane.clientWidth;
    if (fitZoomRef.current === 1 && zoomRef.current === 1) {
      let root = null;
      try { root = frame.contentDocument?.documentElement || null; } catch { root = null; }
      const contentWidth = root?.scrollWidth || 0;
      naturalWidthRef.current = root && contentWidth > root.clientWidth + 1 ? contentWidth : 0;
    }
    const natural = naturalWidthRef.current;
    const next = paneWidth > PHONE_LAYOUT_MAX_WIDTH && natural > paneWidth
      ? Math.max(0.5, Math.floor((paneWidth / natural) * 1000) / 1000)
      : 1;
    fitZoomRef.current = next;
    setFitZoom(next);
  }, []);
  useEffect(() => {
    naturalWidthRef.current = 0;
    fitZoomRef.current = 1;
    setFitZoom(1);
  }, [viewUrl]);
  useEffect(() => {
    const pane = reportFrameRef.current?.parentElement;
    if (!pane || isPdf || !reportReady || typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(() => measureFit());
    observer.observe(pane);
    return () => observer.disconnect();
  }, [isPdf, measureFit, reportReady]);
  const frameZoom = isPdf ? zoom : +(zoom * fitZoom).toFixed(3);
  // Zoomed in, the sheet keeps at least its own width inside the frame (no
  // narrower layout that hides its right column) and the pane scrolls sideways
  // across the whole enlarged sheet. The width is measured from the document
  // whenever it overflows the frame at the current zoom.
  const zoomedIn = !isPdf && zoom > 1;
  const [sheetMinWidth, setSheetMinWidth] = useState(0);
  useEffect(() => { setSheetMinWidth(0); }, [viewUrl]);
  useEffect(() => {
    if (!zoomedIn || !frameLoaded) return undefined;
    let second = 0;
    const first = requestAnimationFrame(() => {
      second = requestAnimationFrame(() => {
        let root = null;
        try { root = reportFrameRef.current?.contentDocument?.documentElement || null; } catch { root = null; }
        if (root && root.scrollWidth > root.clientWidth + 1) {
          const needed = root.scrollWidth;
          setSheetMinWidth((prev) => Math.max(prev, needed));
        }
      });
    });
    return () => { cancelAnimationFrame(first); cancelAnimationFrame(second); };
  }, [zoomedIn, frameZoom, frameLoaded, sheetMinWidth]);

  /* ── Notes state ───────────────────────────── */
  const [notes, setNotes] = useState("");
  const [lastSaved, setLastSaved] = useState(null);
  const [saveError, setSaveError] = useState(false);
  const notesModified = useRef(false);
  const notesRef = useRef(null);
  const latestNotesRef = useRef(notes);
  const latestNotesKeyRef = useRef(notesKey);
  latestNotesRef.current = notes;
  latestNotesKeyRef.current = notesKey;

  const flushNotes = useCallback(() => {
    const key = latestNotesKeyRef.current;
    if (!key || !notesModified.current) return true;
    try {
      notesStorage.setItem(`report_notes_${key}`, latestNotesRef.current);
      notesModified.current = false;
      return true;
    } catch {
      return false;
    }
  }, []);

  /* ── Zoom helpers ──────────────────────────── */
  const MIN_ZOOM = 0.5;
  const MAX_ZOOM = 2;
  const atMinZoom = zoom <= MIN_ZOOM;
  const atMaxZoom = zoom >= MAX_ZOOM;
  const zoomIn = () => setZoom(z => Math.min(+(z + 0.1).toFixed(1), MAX_ZOOM));
  const zoomOut = () => setZoom(z => Math.max(+(z - 0.1).toFixed(1), MIN_ZOOM));
  const zoomReset = () => setZoom(1);

  /* ── Tab helper ────────────────────────────── */
  const openTab = (tab) => { setActiveTab(tab); setPanelOpen(true); };

  /* ── Load notes from localStorage ──────────── */
  useEffect(() => {
    setSaveError(false);
    if (!notesKey) { setNotes(""); setLastSaved(null); return; }
    try {
      let saved = notesStorage.getItem(`report_notes_${notesKey}`);
      if (saved === null) {
        for (const legacyKey of legacyNotesKeys) {
          saved = notesStorage.getItem(`report_notes_${legacyKey}`);
          if (saved !== null) {
            notesStorage.setItem(`report_notes_${notesKey}`, saved);
            break;
          }
        }
      }
      if (saved) {
        setNotes(saved);
        setLastSaved(new Date());
      } else {
        setNotes("");
        setLastSaved(null);
      }
    } catch { setNotes(""); setLastSaved(null); }
    notesModified.current = false;
  }, [legacyNotesKeys, notesKey]);

  /* ── Auto-save notes (500ms debounce) ──────── */
  useEffect(() => {
    if (!notesKey || !notesModified.current) return;
    const timeout = setTimeout(() => {
      try {
        notesStorage.setItem(`report_notes_${notesKey}`, notes);
        notesModified.current = false;
        setLastSaved(new Date());
        setSaveError(false);
      } catch {
        setSaveError(true);
        deskToast({ title: "Notes not saved", description: "Your browser blocked local storage — copy your notes to keep them." });
      }
    }, 500);
    return () => clearTimeout(timeout);
  }, [notes, notesKey]);

  /* Flush a pending final edit before report navigation, reload, or tab close. */
  useEffect(() => {
    const onVisibilityChange = () => {
      if (document.visibilityState === "hidden") flushNotes();
    };
    window.addEventListener("pagehide", flushNotes);
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      window.removeEventListener("pagehide", flushNotes);
      document.removeEventListener("visibilitychange", onVisibilityChange);
      flushNotes();
    };
  }, [flushNotes]);

  /* ── Notes textarea focus ──────────────────── */
  useEffect(() => {
    if (activeTab === "notes" && panelOpen && notesRef.current) {
      const t = setTimeout(() => notesRef.current?.focus(), 300);
      return () => clearTimeout(t);
    }
  }, [activeTab, panelOpen]);

  const handlePrint = useCallback(() => {
    if (!viewUrl || noReport) return;
    flushNotes();

    // HTML reports are already loaded in a same-origin frame, so print that
    // document directly instead of opening a second viewer tab.
    if (!isPdf) {
      try {
        const reportWindow = reportFrameRef.current?.contentWindow;
        if (reportWindow) {
          reportWindow.focus();
          reportWindow.print();
          return;
        }
      } catch {
        // Fall through to the isolated print frame below.
      }
    }

    // PDF browser plugins do not expose a reliable window through <object>.
    // Load the inline document into a temporary frame and invoke
    // the browser's native print dialog once the document is ready.
    const printFrame = document.createElement("iframe");
    printFrame.title = "Print report";
    printFrame.style.position = "fixed";
    printFrame.style.width = "1px";
    printFrame.style.height = "1px";
    printFrame.style.right = "0";
    printFrame.style.bottom = "0";
    printFrame.style.opacity = "0";
    printFrame.style.pointerEvents = "none";
    let cleanupTimer;
    const cleanup = () => {
      if (cleanupTimer) clearTimeout(cleanupTimer);
      printFrame.remove();
    };
    printFrame.onload = () => {
      try {
        const printWindow = printFrame.contentWindow;
        if (!printWindow) throw new Error("Print frame unavailable");
        printWindow.addEventListener("afterprint", cleanup, { once: true });
        printWindow.focus();
        printWindow.print();
      } catch {
        cleanup();
        deskToast({ title: "Print unavailable", description: "Use Download PDF and print it from your PDF viewer." });
      }
    };
    printFrame.onerror = () => {
      cleanup();
      deskToast({ title: "Print unavailable", description: "The report could not be loaded for printing." });
    };
    printFrame.src = viewUrl;
    cleanupTimer = setTimeout(cleanup, 60000);
    document.body.appendChild(printFrame);
  }, [viewUrl, flushNotes, isPdf, noReport]);

  /* ── Keyboard shortcuts ────────────────────── */
  const handleViewerShortcut = useCallback((e) => {
    // `e.target` is important here: shortcuts can originate in the same-origin
    // report iframe, where the parent document's activeElement is just IFRAME.
    const tag = e.target?.tagName || document.activeElement?.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || e.target?.isContentEditable) return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;

    switch (e.key) {
      case "1": e.preventDefault(); if (!noReport) { setActiveTab("sources"); setPanelOpen(true); } break;
      case "2": e.preventDefault(); if (!noReport) { setActiveTab("notes"); setPanelOpen(true); } break;
      case "Escape":
        if (shortcutsOpen) setShortcutsOpen(false);
        else if (isFullscreen) setIsFullscreen(false);
        else setPanelOpen(false);
        break;
      case "+": case "=": e.preventDefault(); if (!noReport) setZoom(z => Math.min(+(z + 0.1).toFixed(1), 2)); break;
      case "-": e.preventDefault(); if (!noReport) setZoom(z => Math.max(+(z - 0.1).toFixed(1), 0.5)); break;
      case "0": e.preventDefault(); if (!noReport) setZoom(1); break;
      case "f": case "F": e.preventDefault(); setIsFullscreen(f => !f); break;
      case "p": case "P": e.preventDefault(); handlePrint(); break;
      case "?": e.preventDefault(); setShortcutsOpen(s => !s); break;
      default: break;
    }
  }, [handlePrint, isFullscreen, noReport, shortcutsOpen]);

  useEffect(() => {
    window.addEventListener("keydown", handleViewerShortcut);
    return () => window.removeEventListener("keydown", handleViewerShortcut);
  }, [handleViewerShortcut]);

  useEffect(() => {
    const frame = reportFrameRef.current;
    if (!frame || isPdf) return undefined;
    let boundWindow = null;
    const bind = () => {
      try {
        boundWindow?.removeEventListener("keydown", handleViewerShortcut);
        boundWindow = frame.contentWindow;
        boundWindow?.addEventListener("keydown", handleViewerShortcut);
      } catch {
        boundWindow = null;
      }
    };
    frame.addEventListener("load", bind);
    bind();
    return () => {
      frame.removeEventListener("load", bind);
      try { boundWindow?.removeEventListener("keydown", handleViewerShortcut); } catch { /* The iframe may have navigated away or been removed. */ }
    };
  }, [viewUrl, handleViewerShortcut, isPdf, reportReady]);

  // Lay the desk canvas under the sheet each time the frame loads a document.
  useEffect(() => {
    const frame = reportFrameRef.current;
    if (!frame || isPdf) return undefined;
    const dress = () => dressReportFrame(frame);
    frame.addEventListener("load", dress);
    dress();
    return () => frame.removeEventListener("load", dress);
  }, [viewUrl, isPdf, reportReady]);

  /* ── Escape closes the shortcuts modal / mobile panel ──
     The main shortcut handler ignores Escape while focus is in an input, which
     leaves the shortcuts modal and the full-screen mobile panel stuck open when
     the user is typing. This dedicated listener handles those two overlays
     regardless of focus (idempotent with the main handler). */
  useEffect(() => {
    if (!shortcutsOpen && !(isMobile && panelOpen)) return;
    const onEsc = (e) => {
      if (e.key !== "Escape") return;
      if (shortcutsOpen) setShortcutsOpen(false);
      else if (isMobile && panelOpen) setPanelOpen(false);
    };
    window.addEventListener("keydown", onEsc);
    return () => window.removeEventListener("keydown", onEsc);
  }, [shortcutsOpen, isMobile, panelOpen]);

  useEffect(() => {
    if (!isMobile || !panelOpen) return undefined;
    mobileReturnFocusRef.current = document.activeElement;
    const frame = requestAnimationFrame(() => mobilePanelRef.current?.focus({ preventScroll: true }));
    return () => {
      cancelAnimationFrame(frame);
      const previous = mobileReturnFocusRef.current;
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus({ preventScroll: true });
    };
  }, [isMobile, panelOpen]);

  useEffect(() => {
    if (!shortcutsOpen) return undefined;
    shortcutsReturnFocusRef.current = document.activeElement;
    const frame = requestAnimationFrame(() => shortcutsRef.current?.focus({ preventScroll: true }));
    return () => {
      cancelAnimationFrame(frame);
      const previous = shortcutsReturnFocusRef.current;
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus({ preventScroll: true });
    };
  }, [shortcutsOpen]);

  /* ── Notes handlers ────────────────────────── */
  const handleNotesChange = (e) => {
    setNotes(e.target.value);
    notesModified.current = true;
  };

  const insertTemplate = (text) => {
    if (notesRef.current) {
      const el = notesRef.current;
      const start = el.selectionStart;
      const prefix = notes.length > 0 && !notes.endsWith("\n") ? "\n\n" : "";
      const newText = notes.slice(0, start) + prefix + text + notes.slice(start);
      setNotes(newText);
      notesModified.current = true;
      setTimeout(() => {
        el.selectionStart = el.selectionEnd = start + prefix.length + text.length;
        el.focus();
      }, 0);
    } else {
      setNotes(prev => (prev ? prev + "\n\n" : "") + text);
      notesModified.current = true;
    }
  };

  const clearNotes = () => {
    setNotes("");
    notesModified.current = true;
    if (notesKey) {
      try { notesStorage.removeItem(`report_notes_${notesKey}`); } catch { /* Notes are already cleared in memory if browser storage is blocked. */ }
    }
    setLastSaved(null);
  };

  const copyNotes = () => {
    navigator.clipboard.writeText(notes).then(() => {
      deskToast({ title: "Notes copied", description: "Copied to clipboard" });
    }).catch(() => deskToast({ title: "Copy failed", description: "Your browser blocked clipboard access." }));
  };

  /* ── Action handlers ───────────────────────── */
  // The same link and toast as the ready screen's Share: this report's #/Viewer page.
  const handleShare = () => { copyReportShareLink({ url, title, jobId: normalizedRequestedJobId }, deskToast); };

  /* ── Filtered sources ──────────────────────── */
  const { webSources, edinetSources, allWebCount, allEdinetCount } = useMemo(() => {
    const q = sourceFilter.trim().toLowerCase();
    let web = [], edinet = [], allWeb = 0, allEdinet = 0;
    for (const s of sources) {
      const isEdinet = s.type === "edinet";
      if (isEdinet) allEdinet++; else allWeb++;
      if (q && !((s.title || "").toLowerCase().includes(q) || (s.url || "").toLowerCase().includes(q) || (s.snippet || "").toLowerCase().includes(q))) continue;
      if (isEdinet) edinet.push(s); else web.push(s);
    }
    return { webSources: web, edinetSources: edinet, allWebCount: allWeb, allEdinetCount: allEdinet };
  }, [sources, sourceFilter]);
  const wordCount = notes.trim() ? notes.trim().split(/\s+/).length : 0;

  return (
    <div className="viewer-desk h-dvh flex flex-col bg-[#eceef2] text-[#0e1420] overflow-hidden">
      {/* The light loader's track is drawn for white; on the desk canvas it needs a hairline tone. */}
      <style>{`.viewer-desk .ndg-loader-track { background: #dfe3e8; }`}</style>

      {/* ── Header ──────────────────────────────────────── */}
      <AnimatePresence>
        {!isFullscreen && (
          <motion.header
            initial={false}
            animate={{ height: 56, opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
            className="shrink-0 bg-white border-b border-[#dfe3e8] flex items-center px-5 gap-3 z-30 overflow-hidden"
          >
            {/* Left: Back + Company */}
            <button
              onClick={() => navigate("/Reports", { state: { openContent: true } })}
              aria-label="Back to Reports"
              className="flex items-center gap-1.5 text-[#5b6472] hover:text-[#0e1420] transition-colors text-sm"
            >
              <ArrowLeft className="w-4 h-4" />
              <span className="hidden sm:inline text-[13px]">Back</span>
            </button>

            {!noReport && <div className="h-4 w-px bg-[#dfe3e8]" />}

            <div className="flex items-center gap-2.5 min-w-0">
              {ticker && (
                <span className="px-2 py-0.5 rounded-md bg-[#0e1420] text-white text-[11px] font-bold font-mono shrink-0">
                  {ticker}
                </span>
              )}
              <p className="text-[13px] text-[#0e1420] truncate font-medium">{companyName}</p>
            </div>

            <div className="flex-1" />

            {/* The report tools appear only while a report can be shown. */}
            {!noReport && (<>
            {/* Center: Zoom controls */}
            <div className={`hidden sm:flex items-center gap-0.5 px-1 py-0.5 rounded-xl bg-white ring-1 ring-[#dfe3e8]${noReport ? " opacity-40 pointer-events-none" : ""}`}>
              <button onClick={zoomOut} disabled={noReport || atMinZoom} aria-disabled={noReport || atMinZoom ? "true" : undefined} aria-label="Zoom out" className="w-6 h-6 rounded-lg flex items-center justify-center text-[#0e1420] hover:bg-[#f1f3f6] transition-all disabled:opacity-40 disabled:pointer-events-none" title={atMinZoom ? "Smallest zoom (50%)" : "Zoom out (-)"}>
                <ZoomOut className="w-3 h-3" />
              </button>
              <button onClick={zoomReset} disabled={noReport} className="px-2 py-0.5 rounded-lg text-[10px] font-mono text-[#5b6472] hover:text-[#0e1420] hover:bg-[#f1f3f6] transition-all min-w-[40px] text-center" title="Reset zoom (0)">
                {Math.round(frameZoom * 100)}%
              </button>
              <button onClick={zoomIn} disabled={noReport || atMaxZoom} aria-disabled={noReport || atMaxZoom ? "true" : undefined} aria-label="Zoom in" className="w-6 h-6 rounded-lg flex items-center justify-center text-[#0e1420] hover:bg-[#f1f3f6] transition-all disabled:opacity-40 disabled:pointer-events-none" title={atMaxZoom ? "Largest zoom (200%)" : "Zoom in (+)"}>
                <ZoomIn className="w-3 h-3" />
              </button>
            </div>

            {/* Mobile: surface Download (highest-value action). The rest stay
                desktop-only — pinch-zoom is native and print is rare on phones. */}
            {shownReport?.pdf && (
              <a href={safeSameOriginPath(shownReport.pdf)} target="_blank" rel="noreferrer" aria-label="Download PDF" className="sm:hidden w-10 h-10 rounded-lg flex items-center justify-center text-[#0e1420] hover:bg-[#f1f3f6] active:bg-[#f1f3f6] transition-all">
                <Download className="w-4 h-4" />
              </a>
            )}

            {/* Actions */}
            <div className="hidden sm:flex items-center gap-1">
              <button onClick={() => setIsFullscreen(true)} className="w-7 h-7 rounded-lg flex items-center justify-center text-[#0e1420] hover:bg-[#f1f3f6] transition-all" title="Fullscreen (F)">
                <Maximize2 className="w-3.5 h-3.5" />
              </button>
              <button onClick={handlePrint} disabled={noReport} className="w-7 h-7 rounded-lg flex items-center justify-center text-[#0e1420] hover:bg-[#f1f3f6] transition-all disabled:opacity-40 disabled:pointer-events-none" title="Print (P)">
                <Printer className="w-3.5 h-3.5" />
              </button>
              {shownReport?.pdf && (
                <a href={safeSameOriginPath(shownReport.pdf)} target="_blank" rel="noreferrer" className="w-7 h-7 rounded-lg flex items-center justify-center text-[#0e1420] hover:bg-[#f1f3f6] transition-all" title="Download PDF">
                  <Download className="w-3.5 h-3.5" />
                </a>
              )}
              <button onClick={handleShare} disabled={noReport} className="w-7 h-7 rounded-lg flex items-center justify-center text-[#0e1420] hover:bg-[#f1f3f6] transition-all disabled:opacity-40 disabled:pointer-events-none" title="Copy link" aria-label="Copy link">
                <Share2 className="w-3.5 h-3.5" />
              </button>
            </div>

            <div className="h-4 w-px bg-[#dfe3e8] hidden sm:block" />
            </>)}

            {/* Panel buttons */}
            <div className="flex items-center gap-1.5">
              {sources.length > 0 && (
                <button
                  onClick={() => openTab("sources")}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-[11px] font-medium transition-all duration-200 ${
                    panelOpen && activeTab === "sources"
                      ? "bg-[#e9edf5] text-[#0e1420] ring-1 ring-[#d3dbe8]"
                      : "bg-white text-[#0e1420] hover:bg-[#f1f3f6] ring-1 ring-[#dfe3e8]"
                  }`}
                >
                  <BookOpen className="w-3 h-3" />
                  <span className="font-mono">{sources.length}</span>
                  <span className="hidden sm:inline">sources</span>
                </button>
              )}

              {!noReport && <button
                onClick={() => openTab("notes")}
                aria-label="Notes"
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-[11px] font-medium transition-all duration-200 ${
                  panelOpen && activeTab === "notes"
                    ? "bg-[#e9edf5] text-[#0e1420] ring-1 ring-[#d3dbe8]"
                    : "bg-white text-[#0e1420] hover:bg-[#f1f3f6] ring-1 ring-[#dfe3e8]"
                }`}
              >
                <PenLine className="w-3 h-3" />
                <span className="hidden sm:inline">Notes</span>
                {notes && <span className="w-1.5 h-1.5 rounded-full bg-[#d97706]" />}
              </button>}

              {panelOpen && (
                <button
                  onClick={() => setPanelOpen(false)}
                  aria-label="Close panel"
                  className="w-7 h-7 rounded-lg flex items-center justify-center text-[#0e1420] hover:bg-[#f1f3f6] transition-all"
                >
                  <X className="w-4 h-4" />
                </button>
              )}
            </div>
          </motion.header>
        )}
      </AnimatePresence>

      {/* Gradient accent line */}
      {!isFullscreen && <div className="h-px shrink-0" />}

      {/* ── Fullscreen exit bar ──────────────────────────── */}
      <AnimatePresence>
        {isFullscreen && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            transition={{ duration: 0.2 }}
            className="fixed top-3 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3 px-4 py-2 rounded-2xl bg-white border border-[#dfe3e8] shadow-[0_8px_28px_rgba(14,20,32,0.12)]"
          >
            <button type="button" aria-label="Exit fullscreen" onClick={() => setIsFullscreen(false)} className="text-[#0e1420] hover:text-[#5b6472] transition">
              <Minimize2 className="w-3.5 h-3.5" />
            </button>
            <span className="text-[10px] text-[#5b6472]">
              Press <kbd className="px-1.5 py-0.5 rounded-md bg-[#f1f3f6] text-[#0e1420] font-mono text-[9px] ring-1 ring-[#dfe3e8]">F</kbd> or <kbd className="px-1.5 py-0.5 rounded-md bg-[#f1f3f6] text-[#0e1420] font-mono text-[9px] ring-1 ring-[#dfe3e8]">Esc</kbd> to exit
            </span>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Main layout ─────────────────────────────────── */}
      <div className="flex-1 flex overflow-hidden">

        {/* ── Report content ─────────────────────────── */}
        <main className="flex-1 overflow-hidden">
          {!url ? (
            <div className="flex flex-col items-center justify-center h-full gap-4 px-6 text-center" role="alert">
              <AlertCircle className="w-8 h-8 text-[#b45309]" aria-hidden="true" />
              <p className="text-[14px] font-medium text-[#0e1420]">This report could not be opened.</p>
              <p className="text-[12px] text-[#5b6472] max-w-sm">The link does not name a report file. Open the report from your Reports page.</p>
              <button
                onClick={() => navigate("/Reports", { state: { openContent: true } })}
                className="px-4 py-2 rounded-xl bg-white ring-1 ring-[#dfe3e8] hover:bg-[#f1f3f6] text-[#0e1420] text-[13px] font-medium transition-colors"
              >
                Back to Reports
              </button>
            </div>
          ) : reportUnavailable ? (
            <div className="flex flex-col items-center justify-center h-full gap-4 px-6 text-center" role="alert">
              <AlertCircle className="w-8 h-8 text-[#b45309]" aria-hidden="true" />
              <p className="text-[14px] font-medium text-[#0e1420]">This report is unavailable or was deleted.</p>
              <button
                onClick={() => navigate("/Reports", { state: { openContent: true } })}
                className="px-4 py-2 rounded-xl bg-white ring-1 ring-[#dfe3e8] hover:bg-[#f1f3f6] text-[#0e1420] text-[13px] font-medium transition-colors"
              >
                Back to Reports
              </button>
            </div>
          ) : !reportReady ? (
            <div className="h-full flex items-center justify-center bg-[#eceef2]" aria-busy="true">
              <IndagoLoader label="Opening report…" />
            </div>
          ) : (
            <div className="h-full overflow-hidden">
              {isPdf ? (
                <div className="h-full overflow-auto">
                  <div style={zoom !== 1 ? { transform: `scale(${zoom})`, transformOrigin: "top left", width: `${100 / zoom}%`, height: `${100 / zoom}%` } : undefined}>
                    <object data={viewUrl} type="application/pdf" className="w-full h-full" style={{ background: "white", minHeight: "100dvh" }}>
                      <p className="p-6 text-gray-800">
                        PDF preview unavailable. <a className="text-blue-600 underline" href={viewUrl} target="_blank" rel="noreferrer">Open in new tab</a>.
                      </p>
                    </object>
                  </div>
                </div>
              ) : (
                <div className={`h-full relative${zoomedIn ? " overflow-x-auto overflow-y-hidden" : ""}`} data-testid="report-frame-pane">
                  {!frameLoaded && (
                    <div className="absolute inset-0 z-[1] flex items-center justify-center bg-[#eceef2]" aria-busy="true">
                      <IndagoLoader label="Opening report…" />
                    </div>
                  )}
                  <iframe
                    ref={reportFrameRef}
                    src={viewUrl}
                    title={title}
                    className="bg-[#eceef2] border-0"
                    onLoad={handleFrameLoad}
                    style={frameZoom !== 1
                      ? { transform: `scale(${frameZoom})`, transformOrigin: "top left", width: zoomedFrameWidth(frameZoom, zoomedIn ? sheetMinWidth : 0), height: `${100 / frameZoom}%` }
                      : { width: "100%", height: "100%" }
                    }
                  />
                </div>
              )}
            </div>
          )}
        </main>

        {/* ── Right panel ────────────────────────────── */}
        <AnimatePresence>
          {panelOpen && (
            <motion.div
              ref={mobilePanelRef}
              role={isMobile ? "dialog" : undefined}
              aria-modal={isMobile ? "true" : undefined}
              aria-label={isMobile ? "Report research tools" : undefined}
              tabIndex={isMobile ? -1 : undefined}
              onKeyDown={(event) => { if (isMobile) trapFocus(event, mobilePanelRef.current); }}
              initial={{ width: 0, opacity: 0 }}
              animate={{ width: isMobile ? "100vw" : 440, opacity: 1 }}
              exit={{ width: 0, opacity: 0 }}
              transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
              className={`shrink-0 border-l border-[#dfe3e8] bg-white flex flex-col overflow-hidden h-full ${isMobile ? "fixed inset-0 z-40" : ""}`}
              style={{ maxWidth: isMobile ? "100vw" : "85vw" }}
            >
              <div style={{ width: isMobile ? "100%" : "min(440px, 85vw)" }} className="flex flex-col h-full">

                {/* Mobile: the panel covers the header, so it needs its own close. */}
                {isMobile && (
                  <div className="shrink-0 flex justify-end px-3 pt-3">
                    <button
                      onClick={() => setPanelOpen(false)}
                      aria-label="Close panel"
                      className="w-11 h-11 rounded-lg flex items-center justify-center text-[#0e1420] hover:bg-[#f1f3f6] transition-all"
                    >
                      <X className="w-5 h-5" />
                    </button>
                  </div>
                )}

                {/* ── Tab bar ───────────────────────── */}
                <div className="shrink-0 px-5 pt-4 pb-0">
                  <div className="flex gap-0.5 p-[3px] rounded-[14px] bg-[#f1f3f6]">
                    {[
                      { id: "sources", label: "Sources", icon: BookOpen, badge: sources.length > 0 ? sources.length : null, badgeColor: "bg-[#e3ecff] text-[#1d4ed8]" },
                      { id: "notes", label: "Notes", icon: PenLine, dot: !!notes },
                    ].map(tab => {
                      const Icon = tab.icon;
                      const isActive = activeTab === tab.id;
                      return (
                        <button
                          key={tab.id}
                          onClick={() => setActiveTab(tab.id)}
                          className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-[9px] min-h-[44px] rounded-[11px] text-[12px] font-medium transition-all duration-300 active:scale-[0.98] ${
                            isActive
                              ? "bg-white text-[#0e1420] shadow-[0_1px_3px_rgba(14,20,32,0.08),0_0_0_1px_rgba(14,20,32,0.06)]"
                              : "text-[#5b6472] hover:text-[#0e1420]"
                          }`}
                        >
                          <Icon className="w-3.5 h-3.5" />
                          {tab.label}
                          {tab.badge != null && (
                            <span className={`font-mono text-[9px] px-1.5 py-px rounded-md font-semibold ${
                              isActive ? tab.badgeColor : "bg-[#e6e9ee] text-[#5b6472]"
                            }`}>
                              {tab.badge}
                            </span>
                          )}
                          {tab.dot && (
                            <span className="w-[5px] h-[5px] rounded-full bg-[#d97706]" />
                          )}
                        </button>
                      );
                    })}
                  </div>
                  <button
                    onClick={() => navigate("/DeepResearch")}
                    className="flex items-center justify-center gap-1.5 mt-2 mx-auto px-4 py-1.5 rounded-xl text-[10px] font-medium text-[#5b6472] hover:text-[#0e1420] hover:bg-[#f1f3f6] ring-1 ring-transparent hover:ring-[#dfe3e8] transition-all duration-200"
                  >
                    <Terminal className="w-3 h-3" />
                    Open Callisto
                    <ExternalLink className="w-2.5 h-2.5 opacity-40" />
                  </button>
                </div>

                <div className="h-px bg-[#eceff3] mx-5 mt-2" />

                {/* ── Tab content ────────────────────── */}
                {activeTab === "sources" ? (

                  /* ── Sources tab ──────────────────── */
                  <div className="flex-1 flex flex-col overflow-hidden">
                    <div className="shrink-0 px-4 py-3 space-y-3">
                      <div className="flex items-center gap-3 text-[11px]">
                        <span className="flex items-center gap-1.5 text-[#5b6472]">
                          <Globe className="w-3 h-3 text-[#1d4ed8]" />
                          <span className="font-mono text-[#1d4ed8]">{allWebCount}</span>
                          <span>Web</span>
                        </span>
                        <span className="text-[#9aa2ae]">&middot;</span>
                        <span className="flex items-center gap-1.5 text-[#5b6472]">
                          <Database className="w-3 h-3 text-[#8a5a00]" />
                          <span className="font-mono text-[#8a5a00]">{allEdinetCount}</span>
                          <span>SEC</span>
                        </span>
                      </div>

                      {sources.length > 5 && (
                        <div className="relative">
                          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[#7b8494]" />
                          <input
                            type="text"
                            value={sourceFilter}
                            onChange={(e) => setSourceFilter(e.target.value)}
                            placeholder="Filter sources..."
                            className="w-full bg-white border border-[#dfe3e8] rounded-xl pl-9 pr-3 py-2 text-[12px] text-[#0e1420] placeholder-[#7b8494] outline-none focus:border-[#0e1420] focus:ring-2 focus:ring-[#0e1420]/10 transition-colors"
                          />
                        </div>
                      )}
                    </div>

                    <div className="flex-1 overflow-y-auto px-4 pb-4 space-y-4 viewer-scroll">
                      {edinetSources.length > 0 && (
                        <div>
                          <div className="flex items-center gap-2 mb-2 px-1">
                            <FileText className="w-3.5 h-3.5 text-[#8a5a00]" />
                            <span className="text-[10px] font-semibold uppercase tracking-wider text-[#5b6472]">SEC Filings</span>
                            <span className="text-[10px] text-[#5b6472] font-mono ml-auto">{edinetSources.length}</span>
                          </div>
                          <div className="space-y-1.5">
                            {edinetSources.map((s, i) => (
                              <SourceCard key={s.id || `e-${i}`} source={s} index={i} />
                            ))}
                          </div>
                        </div>
                      )}

                      {webSources.length > 0 && (
                        <div>
                          <div className="flex items-center gap-2 mb-2 px-1">
                            <Globe className="w-3.5 h-3.5 text-[#1d4ed8]" />
                            <span className="text-[10px] font-semibold uppercase tracking-wider text-[#5b6472]">Web Sources</span>
                            <span className="text-[10px] text-[#5b6472] font-mono ml-auto">{webSources.length}</span>
                          </div>
                          <div className="space-y-1.5">
                            {webSources.map((s, i) => (
                              <SourceCard key={s.id || `w-${i}`} source={s} index={i} />
                            ))}
                          </div>
                        </div>
                      )}

                      {sources.length === 0 && (
                        <div className="flex flex-col items-center justify-center py-16 text-center">
                          <BookOpen className="w-8 h-8 text-[#b8bfc9] mb-3" />
                          <p className="text-[13px] text-[#5b6472]">No sources available</p>
                          <p className="text-[11px] text-[#5b6472] mt-1">Sources will appear here when viewing reports</p>
                        </div>
                      )}

                      {sourceFilter && webSources.length === 0 && edinetSources.length === 0 && sources.length > 0 && (
                        <div className="text-center py-8">
                          <p className="text-[12px] text-[#5b6472]">No sources match &ldquo;{sourceFilter}&rdquo;</p>
                        </div>
                      )}
                    </div>
                  </div>

                ) : (

                  /* ── Notes tab ────────────────────── */
                  bindingPending ? (
                    <div className="flex-1 flex items-center justify-center px-6 text-center" role="status">
                      <p className="text-[12px] text-[#5b6472]">Linking this report…</p>
                    </div>
                  ) : bindingMismatch ? (
                    <div className="flex-1 flex flex-col items-center justify-center px-6 text-center">
                      <AlertCircle className="w-8 h-8 text-[#b45309] mb-3" />
                      <p className="text-[13px] font-medium text-[#0e1420]">Notes are unavailable</p>
                      <p className="text-[11px] text-[#5b6472] mt-1 max-w-xs">
                        This report file does not belong to the requested job. Open it from report history to keep notes attached to the correct report.
                      </p>
                      <p className="text-[11px] text-[#5b6472] mt-1 max-w-xs">
                        A shared link opens notes only for the account that generated the report.
                      </p>
                    </div>
                  ) : (
                  <div className="flex-1 flex flex-col overflow-hidden">
                    {/* Templates */}
                    <div className="shrink-0 px-4 py-3">
                      <div className="flex flex-wrap gap-1.5">
                        {NOTE_TEMPLATES.map(t => (
                          <button
                            key={t.label}
                            onClick={() => insertTemplate(t.text)}
                            className="px-2.5 py-1 rounded-lg bg-white ring-1 ring-[#dfe3e8] text-[10px] text-[#5b6472] hover:text-[#0e1420] hover:bg-[#f1f3f6] hover:ring-[#d3d8df] transition-all"
                          >
                            {t.label}
                          </button>
                        ))}
                      </div>
                    </div>

                    {/* Textarea */}
                    <div className="flex-1 px-4 pb-2">
                      <textarea
                        ref={notesRef}
                        value={notes}
                        onChange={handleNotesChange}
                        maxLength={50000}
                        placeholder="Your investment notes...&#10;&#10;Use the templates above to get started, or just type freely."
                        className="w-full h-full bg-white border border-[#dfe3e8] rounded-xl p-4 text-base sm:text-[13px] text-[#0e1420] placeholder-[#7b8494] outline-none focus:border-[#0e1420] focus:ring-2 focus:ring-[#0e1420]/10 resize-none font-mono leading-relaxed tracking-[-0.01em] transition-colors viewer-scroll"
                      />
                    </div>

                    {/* Notes footer */}
                    <div className="shrink-0 px-4 pb-4 flex items-center gap-3 text-[10px] text-[#5b6472]">
                      {saveError ? (
                        <span className="flex items-center gap-1 text-[#b45309]">
                          <AlertCircle className="w-2.5 h-2.5" />
                          Not saved
                        </span>
                      ) : lastSaved && (
                        <span className="flex items-center gap-1 text-[#047857]">
                          <Check className="w-2.5 h-2.5" />
                          Saved
                        </span>
                      )}
                      {wordCount > 0 && (
                        <span className="font-mono">{wordCount} words</span>
                      )}
                      <div className="flex-1" />
                      {notes && (
                        <>
                          <button
                            onClick={copyNotes}
                            className="p-1 rounded hover:text-[#0e1420] hover:bg-[#f1f3f6] transition-all"
                            title="Copy notes"
                          >
                            <Copy className="w-3 h-3" />
                          </button>
                          <button
                            onClick={clearNotes}
                            className="p-1 rounded hover:text-[#b91c1c] hover:bg-[#fdecec] transition-all"
                            title="Clear notes"
                          >
                            <Trash2 className="w-3 h-3" />
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                  )
                )}
              </div>

              {/* Custom scrollbar */}
              <style>{`
                .viewer-scroll::-webkit-scrollbar { width: 3px; }
                .viewer-scroll::-webkit-scrollbar-track { background: transparent; }
                .viewer-scroll::-webkit-scrollbar-thumb { background: rgba(14,20,32,0.16); border-radius: 3px; }
                .viewer-scroll::-webkit-scrollbar-thumb:hover { background: rgba(14,20,32,0.28); }
              `}</style>
            </motion.div>
          )}
        </AnimatePresence>

      </div>

      {/* ── Status bar ──────────────────────────────────── */}
      {!isFullscreen && (
        <div className="shrink-0 h-7 bg-[#f6f7f9] border-t border-[#dfe3e8] flex items-center px-5 gap-4 text-[10px] text-[#5b6472] font-mono">
          {shownReport?.finishedAt && (
            <span className="flex items-center gap-1.5">
              <Clock className="w-2.5 h-2.5" />
              {new Date(shownReport.finishedAt).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
            </span>
          )}
          {sources.length > 0 && (
            <span>{sources.length} sources ({allEdinetCount} SEC, {allWebCount} Web)</span>
          )}
          <div className="flex-1" />
          {frameZoom !== 1 && !noReport && <span>{Math.round(frameZoom * 100)}%</span>}
          <button onClick={() => setShortcutsOpen(true)} className="flex items-center gap-1 hover:text-[#0e1420] transition">
            <Keyboard className="w-2.5 h-2.5" />
            <span>?</span>
          </button>
        </div>
      )}

      {/* ── Keyboard shortcuts modal ────────────────────── */}
      <AnimatePresence>
        {shortcutsOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-[60] flex items-center justify-center bg-[#0e1420]/30"
            onClick={() => setShortcutsOpen(false)}
          >
            <motion.div
              ref={shortcutsRef}
              role="dialog"
              aria-modal="true"
              aria-labelledby="viewer-shortcuts-title"
              tabIndex={-1}
              onKeyDown={(event) => trapFocus(event, shortcutsRef.current)}
              initial={{ opacity: 0, scale: 0.95, y: 10 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 10 }}
              transition={{ duration: 0.2 }}
              className="bg-white rounded-2xl border border-[#dfe3e8] p-6 max-w-xs w-full shadow-[0_24px_64px_rgba(14,20,32,0.18)]"
              onClick={e => e.stopPropagation()}
            >
              <div className="flex items-center justify-between mb-5">
                <div className="flex items-center gap-2">
                  <Keyboard className="w-4 h-4 text-[#5b6472]" />
                  <h3 id="viewer-shortcuts-title" className="text-[14px] font-semibold text-[#0e1420]">Keyboard Shortcuts</h3>
                </div>
                <button aria-label="Close keyboard shortcuts" onClick={() => setShortcutsOpen(false)} className="text-[#5b6472] hover:text-[#0e1420] transition">
                  <X className="w-4 h-4" />
                </button>
              </div>
              <div className="space-y-2.5">
                {SHORTCUTS.map(s => (
                  <div key={s.desc} className="flex items-center justify-between">
                    <span className="text-[12px] text-[#5b6472]">{s.desc}</span>
                    <div className="flex gap-1">
                      {s.keys.map(k => (
                        <kbd key={k} className="px-2 py-0.5 rounded-md bg-[#f1f3f6] text-[#0e1420] text-[11px] font-mono ring-1 ring-[#dfe3e8] min-w-[26px] text-center">
                          {k}
                        </kbd>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
              <div className="mt-5 pt-3 border-t border-[#e6e9ee]">
                <p className="text-[10px] text-[#5b6472] text-center">Shortcuts are disabled when typing in inputs</p>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>



    </div>
  );
}

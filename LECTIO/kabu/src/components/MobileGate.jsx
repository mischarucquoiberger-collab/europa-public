import React, { useCallback, useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";

/**
 * MobileGate — the phone-only screen shown IN PLACE OF a desktop-only page.
 *
 * The dense, interactive surfaces (the report tools) are built for a large
 * canvas. On a
 * phone we don't shrink them — we replace them with this: a quiet, typographic
 * card that reads like a spec sheet, states the facts, and turns the dead end
 * into a HANDOFF: one tap copies the exact deep link the visitor was opening,
 * so they can finish on a desktop. The two mobile-ready surfaces (Deep
 * Research, Home) are one tap away.
 *
 * Deliberately restrained: no motion beyond a 300 ms fade, no decoration. It
 * renders instead of the page, so no heavy page effect or provider request
 * ever fires on a phone. Light palette so the fixed INDAGO wordmark + Dashboard
 * toggle (black, drawn by Layout above this) stay legible and usable.
 *
 * Props: pageName — the route key of the blocked surface (optional).
 */

const PAGE_LABELS = {
  Reports: "Research Reports",
  GenerateReport: "Report Builder",
  Viewer: "Report Viewer",
};

/* Live viewport size for the SCREEN row — precise beats vague. */
function useViewportSize() {
  const read = () => {
    try { return [window.innerWidth || 0, window.innerHeight || 0]; } catch { return [0, 0]; }
  };
  const [size, setSize] = useState(read);
  useEffect(() => {
    const onResize = () => setSize(read());
    try {
      window.addEventListener("resize", onResize, { passive: true });
      window.addEventListener("orientationchange", onResize, { passive: true });
    } catch { /* no-op */ }
    return () => {
      try {
        window.removeEventListener("resize", onResize);
        window.removeEventListener("orientationchange", onResize);
      } catch { /* no-op */ }
    };
  }, []);
  return size;
}

/* Copy the current URL. Clipboard API first (needs a secure context + a user
   gesture — both true here), a hidden-textarea execCommand fallback second.
   Never throws; returns "copied" | "failed". */
async function copyCurrentUrl() {
  let url = "";
  try { url = window.location.href; } catch { return "failed"; }
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(url);
      return "copied";
    }
  } catch { /* fall through to the legacy path */ }
  try {
    const ta = document.createElement("textarea");
    ta.value = url;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.top = "-1000px";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    ta.setSelectionRange(0, url.length);
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok ? "copied" : "failed";
  } catch {
    return "failed";
  }
}

export default function MobileGate({ pageName }) {
  const location = useLocation();
  const [w, h] = useViewportSize();
  const [copyState, setCopyState] = useState("idle"); // idle | copied | failed
  const resetTimer = useRef(0);

  const label = (pageName && PAGE_LABELS[pageName]) || "This view";

  // A company deep link (CompanyProfile?code=7203) is
  // worth naming on the sheet: the visitor knows exactly what they're handing
  // off. Read-only; we never navigate on it.
  let code = "";
  try {
    const params = new URLSearchParams(location.search || "");
    code = (params.get("code") || params.get("ticker") || "").trim().toUpperCase().slice(0, 8);
  } catch { code = ""; }

  const onCopy = useCallback(async () => {
    const result = await copyCurrentUrl();
    setCopyState(result);
    if (resetTimer.current) window.clearTimeout(resetTimer.current);
    resetTimer.current = window.setTimeout(() => setCopyState("idle"), 2400);
  }, []);

  useEffect(() => () => { if (resetTimer.current) window.clearTimeout(resetTimer.current); }, []);

  const copyLabel =
    copyState === "copied" ? "Link copied"
    : copyState === "failed" ? "Couldn't copy — long-press the address bar"
    : "Copy link for desktop";

  return (
    <div className="mg-root" role="region" aria-label="Desktop required">
      <div className="mg-card">
        <p className="mg-eyebrow">Desktop required</p>
        <h1 className="mg-title">Built for a bigger screen.</h1>
        <p className="mg-sub">
          {label} is a dense, interactive workspace. Open it on a desktop or
          laptop for the full experience.
        </p>

        <dl className="mg-spec" aria-label="Details">
          <div className="mg-row">
            <dt>View</dt>
            <dd>
              {label}
              {code ? <span className="mg-code">{code}</span> : null}
            </dd>
          </div>
          <div className="mg-row">
            <dt>Screen</dt>
            <dd className="mg-mono">{w && h ? `${w} × ${h} px` : "—"}</dd>
          </div>
          <div className="mg-row">
            <dt>Needs</dt>
            <dd>Desktop or laptop</dd>
          </div>
        </dl>

        <button
          type="button"
          className={`mg-copy${copyState === "copied" ? " is-copied" : ""}${copyState === "failed" ? " is-failed" : ""}`}
          onClick={onCopy}
          aria-live="polite"
        >
          {copyState === "copied" ? (
            <svg viewBox="0 0 16 16" className="mg-copy__icon" aria-hidden="true">
              <path d="M3.5 8.5 6.5 11.5 12.5 5" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" fill="none" />
            </svg>
          ) : (
            <svg viewBox="0 0 16 16" className="mg-copy__icon" aria-hidden="true">
              <rect x="5.5" y="5.5" width="8" height="8" rx="1.6" stroke="currentColor" strokeWidth="1.4" fill="none" />
              <path d="M10.5 5.5v-1.4A1.6 1.6 0 0 0 8.9 2.5H4.1a1.6 1.6 0 0 0-1.6 1.6v4.8a1.6 1.6 0 0 0 1.6 1.6h1.4" stroke="currentColor" strokeWidth="1.4" fill="none" strokeLinecap="round" />
            </svg>
          )}
          <span>{copyLabel}</span>
        </button>

        <nav className="mg-links" aria-label="Available on mobile">
          <span className="mg-links__label">On mobile</span>
          <Link to="/DeepResearch" className="mg-link">Callisto</Link>
          <span className="mg-links__dot" aria-hidden="true">·</span>
          <Link to="/Home" className="mg-link">Home</Link>
        </nav>
      </div>

      <style>{`
        .mg-root {
          position: relative;
          min-height: 100vh;
          min-height: 100dvh;
          width: 100%;
          display: flex;
          align-items: flex-start;      /* card centers via margin:auto; top stays reachable */
          justify-content: center;
          padding: max(1.25rem, env(safe-area-inset-top)) 1.25rem
                   max(1.25rem, env(safe-area-inset-bottom));
          overflow-x: hidden;
          background: #0e1420;
          font-family: "Space Grotesk", -apple-system, BlinkMacSystemFont,
                       "SF Pro Text", "Helvetica Neue", Arial, sans-serif;
          color: #f4f5f7;
          -webkit-font-smoothing: antialiased;
        }

        .mg-card {
          position: relative;
          margin: auto;
          width: 100%;
          max-width: 22.5rem;
          padding: 1.9rem 1.6rem 1.5rem;
          border-radius: 1.25rem;
          background: rgba(255,255,255,0.05);
          border: 1px solid rgba(255,255,255,0.12);
          box-shadow: 0 1px 2px rgba(0,0,0,0.2), 0 18px 48px rgba(0,0,0,0.28);
          animation: mgIn 0.32s ease both;
        }
        @keyframes mgIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }

        .mg-eyebrow {
          margin: 0 0 0.9rem;
          font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
          font-size: 0.66rem; font-weight: 500;
          letter-spacing: 0.16em; text-transform: uppercase;
          color: rgba(255,255,255,0.55);
        }
        .mg-title {
          margin: 0 0 0.55rem;
          font-size: 1.5rem; line-height: 1.15; font-weight: 600;
          letter-spacing: -0.02em; color: #f4f5f7;
        }
        .mg-sub {
          margin: 0;
          font-size: 0.9rem; line-height: 1.5;
          color: rgba(255,255,255,0.68);
        }

        /* ── spec sheet ─────────────────────────────────────────────── */
        .mg-spec {
          margin: 1.35rem 0 1.25rem;
          padding: 0;
          border-top: 1px solid rgba(255,255,255,0.14);
          border-bottom: 1px solid rgba(255,255,255,0.14);
        }
        .mg-row {
          display: grid;
          grid-template-columns: 5.2rem 1fr;
          align-items: baseline;
          gap: 0.75rem;
          padding: 0.6rem 0;
        }
        .mg-row + .mg-row { border-top: 1px solid rgba(255,255,255,0.08); }
        .mg-row dt {
          margin: 0;
          font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
          font-size: 0.64rem; font-weight: 500;
          letter-spacing: 0.14em; text-transform: uppercase;
          color: rgba(255,255,255,0.5);
        }
        .mg-row dd {
          margin: 0;
          font-size: 0.86rem; font-weight: 500;
          color: #f4f5f7;
          text-align: right;
          font-variant-numeric: tabular-nums;
        }
        .mg-mono { font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; font-size: 0.8rem; }
        .mg-code {
          display: inline-block;
          margin-left: 0.45rem;
          padding: 0.08rem 0.4rem;
          border-radius: 0.35rem;
          font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
          font-size: 0.72rem; font-weight: 500;
          color: #f4f5f7;
          background: rgba(255,255,255,0.1);
        }

        /* ── copy handoff ───────────────────────────────────────────── */
        .mg-copy {
          width: 100%;
          display: inline-flex; align-items: center; justify-content: center;
          gap: 0.5rem;
          height: 2.75rem;
          border: 0; border-radius: 0.8rem;
          background: #f4f5f7; color: #0e1420;
          font: inherit; font-size: 0.9rem; font-weight: 600; letter-spacing: 0.005em;
          cursor: pointer;
          transition: background 0.18s ease, transform 0.12s ease;
          -webkit-tap-highlight-color: transparent;
        }
        .mg-copy:active { transform: scale(0.985); }
        .mg-copy.is-copied { background: #86efac; }
        .mg-copy.is-failed { background: rgba(255,255,255,0.16); color: #f4f5f7; font-weight: 500; font-size: 0.82rem; }
        .mg-copy:focus-visible { outline: 2px solid #f4f5f7; outline-offset: 3px; }
        .mg-copy__icon { width: 16px; height: 16px; flex: none; }

        /* ── mobile-ready links ─────────────────────────────────────── */
        .mg-links {
          margin-top: 1rem;
          display: flex; align-items: center; justify-content: center;
          gap: 0.55rem;
          font-size: 0.82rem;
          color: rgba(255,255,255,0.58);
        }
        .mg-links__label {
          font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
          font-size: 0.62rem; letter-spacing: 0.14em; text-transform: uppercase;
          margin-right: 0.15rem;
        }
        .mg-links__dot { color: rgba(255,255,255,0.35); }
        .mg-link {
          color: #f4f5f7; font-weight: 600; text-decoration: none;
          border-bottom: 1px solid rgba(255,255,255,0.35);
          padding-bottom: 1px;
          transition: border-color 0.15s ease;
          -webkit-tap-highlight-color: transparent;
        }
        .mg-link:active, .mg-link:hover { border-color: #f4f5f7; }
        .mg-link:focus-visible { outline: 2px solid #f4f5f7; outline-offset: 3px; border-radius: 2px; }

        /* short landscape phones: fit the whole card in ~390 px without scrolling */
        @media (max-height: 470px) {
          .mg-card    { padding: 1.15rem 1.4rem 1.05rem; max-width: 26rem; }
          .mg-eyebrow { margin-bottom: 0.5rem; }
          .mg-title   { font-size: 1.2rem; margin-bottom: 0.35rem; }
          .mg-sub     { font-size: 0.82rem; line-height: 1.4; }
          .mg-spec    { margin: 0.85rem 0 0.8rem; }
          .mg-row     { padding: 0.38rem 0; }
          .mg-copy    { height: 2.5rem; font-size: 0.86rem; }
          .mg-links   { margin-top: 0.7rem; }
        }

        @media (prefers-reduced-motion: reduce) {
          .mg-card { animation: none !important; }
          .mg-copy, .mg-link { transition: none !important; }
        }
      `}</style>
    </div>
  );
}

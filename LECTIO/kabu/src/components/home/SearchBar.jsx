import React, { useState, useRef, useEffect, useMemo, useCallback } from "react";
import { Search, Building2, Loader2, ArrowRight, Clock } from "lucide-react";
import { useCircleTransition } from "@/components/CircleTransition";
import { startReport } from "@/api/backend";
import { normalizeJobId, readReportHistory } from "@/lib/reportStorage";
import { POPULAR_COMPANIES, companyIndexNow, displayCompanyName, findIndexedTicker, loadCompanyIndex, matchCompanyIndex, normalizeUsTicker } from "@/lib/companyIndex";
import useTypingPlaceholder from "@/hooks/useTypingPlaceholder";

const MAX_RESULTS = 20;

// Rotating placeholder examples — each entry shows ONE company at a time so
// users never get the impression that comma-separated multi-company queries
// are supported. Concurrent reports are started by generating one company,
// navigating back, then generating the next — each one becomes its own card
// in the Recent/Generating list.
const HOME_PLACEHOLDER_PHRASES = [
  "Search any company by name or ticker…",
  "NVDA   NVIDIA Corporation",
  "DUOL   Duolingo, Inc.",
  "Try Crocs…",
  "CROX   Crocs, Inc.",
  "AAPL   Apple Inc.",
  "Try Shake Shack…",
  "ETSY   Etsy, Inc.",
  "CELH   Celsius Holdings, Inc.",
  "Try Wingstop…",
  "YETI   YETI Holdings, Inc.",
  "MSFT   Microsoft Corporation",
  "BOOT   Boot Barn Holdings, Inc.",
];

/** The dropdown's matches for a lowercased query (by symbol or by a name
 *  containing it, best match first — see matchCompanyIndex). */
function matchCompanies(index, q) {
  return matchCompanyIndex(index, q, MAX_RESULTS);
}

/**
 * The dropdown rows for the text in the box. Empty text: recents, then popular.
 * Otherwise the list's matches; with none, text shaped like a US ticker (IBM)
 * gets one row that starts a report for that symbol (the backend covers every
 * SEC registrant and supplies the name). Nothing until the list has loaded.
 */
export function dropdownRows(text, index, recents = []) {
  const q = String(text || "").trim().toLowerCase();
  if (!q) {
    if (!recents.length) return POPULAR_COMPANIES;
    const recentTickers = new Set(recents.map((c) => c.tickerLower));
    return [...recents, ...POPULAR_COMPANIES.filter((c) => !recentTickers.has(c.tickerLower))];
  }
  const matches = matchCompanies(index, q);
  if (matches.length || !index) return matches;
  const symbol = normalizeUsTicker(text);
  return symbol ? [{ ticker: symbol, name: "", tickerLower: symbol.toLowerCase(), adHoc: true }] : [];
}

/** The row highlighted by default for this text: the first row once something is typed. */
export function defaultHighlight(text, rows) {
  return String(text || "").trim() && rows.length > 0 ? 0 : -1;
}

/**
 * What Enter or Generate starts, decided from the text in the box at that
 * moment: the highlighted row only if it was highlighted for this very text and
 * is one of its current rows, else the first row, else a listed symbol typed
 * first ("aapl, apple"), else the text itself when it is shaped like a US
 * ticker. Null means nothing to start (the caller shows the error).
 */
export function pickSubmission(text, index, highlight = { text: "", idx: -1 }, recents = []) {
  const rows = dropdownRows(text, index, recents);
  const idx = highlight && highlight.text === text && highlight.idx >= 0 && highlight.idx < rows.length
    ? highlight.idx
    : defaultHighlight(text, rows);
  if (idx >= 0 && rows[idx]) return { ticker: rows[idx].ticker, name: rows[idx].name || "" };
  const trimmed = String(text || "").trim();
  if (!trimmed) return null;
  const listed = findIndexedTicker(index, trimmed.split(/[\s,]+/)[0]);
  if (listed) return { ticker: listed.ticker, name: listed.name };
  const symbol = normalizeUsTicker(trimmed);
  return symbol ? { ticker: symbol, name: "" } : null;
}

/** True when keystrokes on `el` are text entry, so a global "/" must not steal them. */
export function isTypingTarget(el) {
  if (!el || typeof el !== "object") return false;
  const tag = String(el.tagName || "").toUpperCase();
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  return !!el.isContentEditable;
}

export default function SearchBar({ reportHistory = null }) {
  const [query, setQuery] = useState("");
  const [isFocused, setIsFocused] = useState(false);
  // The highlight remembers the text it was chosen for: once the text changes it
  // falls back to the default row for the new text in the same render, so a
  // stale row can never be submitted (see dropdownRows / pickSubmission).
  const [highlight, setHighlight] = useState({ text: "", idx: -1 });
  const inputRef = useRef(null);
  const containerRef = useRef(null);
  const dropdownRef = useRef(null);
  const isKeyNav = useRef(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const { navigateWithReveal } = useCircleTransition();
  // The full company list loads on first use of the box (focus or typing).
  const [companyIndex, setCompanyIndex] = useState(companyIndexNow);
  const waitingForIndex = useRef(false);
  const wantIndex = useCallback(() => {
    if (companyIndexNow()) return;
    loadCompanyIndex().then(setCompanyIndex).catch(() => { /* Popular and recents still work; typing retries. */ });
  }, []);

  // Animated placeholder — freezes when the user starts typing or a submit
  // is in-flight so it never competes with real content.
  const animatedPlaceholder = useTypingPlaceholder(HOME_PLACEHOLDER_PHRASES, {
    active: query === "" && !isSubmitting,
  });

  // Recent companies from user's report history — shown above "Popular"
  const recentCompanies = useMemo(() => {
    try {
      // Home passes its live history state so a report that finishes while this
      // component remains mounted appears immediately. The localStorage fallback
      // preserves this component's standalone/back-compat behavior.
      let hist = reportHistory;
      if (!Array.isArray(hist)) {
        hist = readReportHistory();
      }
      if (!Array.isArray(hist)) return [];
      const seen = new Set();
      const recents = [];
      for (const h of hist) {
        const t = String(h.ticker || "").trim();
        if (!t || seen.has(t)) continue;
        seen.add(t);
        const match = (companyIndex || POPULAR_COMPANIES).find((c) => c.tickerLower === t.toLowerCase());
        if (match) recents.push(match);
        if (recents.length >= 5) break;
      }
      return recents;
    } catch { return []; }
  }, [reportHistory, companyIndex]);

  // The dropdown rows for the text in the box, derived in the same render as the
  // text itself (never one effect late).
  const filteredCompanies = useMemo(
    () => dropdownRows(query, companyIndex, recentCompanies),
    [query, companyIndex, recentCompanies],
  );
  const highlightIdx = highlight.text === query && highlight.idx < filteredCompanies.length
    ? highlight.idx
    : defaultHighlight(query, filteredCompanies);
  const setHighlightIdx = (next) => setHighlight((prev) => {
    const current = prev.text === query && prev.idx < filteredCompanies.length ? prev.idx : defaultHighlight(query, filteredCompanies);
    return { text: query, idx: typeof next === "function" ? next(current) : next };
  });

  useEffect(() => {
    const handler = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setIsFocused(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  useEffect(() => {
    // ⌘K is now owned globally by the command palette (a superset of this box —
    // it can search AND generate a report for a ticker from any page), so this
    // component no longer binds it; keeping both would double-fire on Home.
    // Escape-to-blur stays.
    const handler = (e) => {
      if (e.key === "Escape") {
        inputRef.current?.blur();
        setIsFocused(false);
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);

  // "/" focuses the search from anywhere on Reports — unless the user is
  // already typing somewhere (input, textarea, select, contenteditable) or
  // holds a modifier (⌘/ and Ctrl+/ belong to the shortcut sheet). Shift is
  // allowed: some keyboard layouts need it to produce "/".
  useEffect(() => {
    const handler = (e) => {
      if (e.key !== "/" || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.defaultPrevented || e.isComposing) return;
      if (isTypingTarget(e.target) || isTypingTarget(document.activeElement)) return;
      const input = inputRef.current;
      if (!input || input.disabled) return;
      e.preventDefault();
      input.focus();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);

  // The symbol the backend /start endpoint receives: the first whitespace/comma
  // token, upper-cased, and only when it is shaped like a US symbol (1 to 5
  // letters, optional class suffix such as BRK.B). "aapl, apple" collapses to
  // "AAPL" instead of "AAPLAPPLE"; anything else is refused before a request.
  const sanitizeCode = (raw) => {
    const s = String(raw || "").trim();
    if (!s) return "";
    return normalizeUsTicker(s.split(/[\s,]+/)[0] || s);
  };

  const launchReport = (ticker, name = "", mode = "full", event) => {
    const code = sanitizeCode(ticker);
    if (!code) {
      setError("Enter a valid ticker symbol (e.g. AAPL)");
      return;
    }
    setIsSubmitting(true);
    setError(null);

    const promise = startReport({ stock_code: code, company_name: name, mode })
      .then((response) => {
        const jobId = normalizeJobId(response?.job_id);
        if (!jobId) throw new Error("Job ID missing");
        return `/GenerateReport?jobId=${jobId}&ticker=${encodeURIComponent(code)}&name=${encodeURIComponent(name || "")}&mode=${mode}`;
      })
      .catch((err) => {
        setError(err.message || "Failed to start report");
        return null;
      })
      .finally(() => setIsSubmitting(false));

    navigateWithReveal(promise, event);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (waitingForIndex.current || isSubmitting) return;
    // Decide from the text in the box right now, never from a highlight or a
    // row list computed for earlier text.
    const text = inputRef.current ? inputRef.current.value : query;
    let index = companyIndex;
    if (!index && text.trim()) {
      // Enter pressed before the list arrived: wait for it (one submit at a
      // time), then pick exactly as the dropdown would have.
      waitingForIndex.current = true;
      setIsSubmitting(true);
      try {
        index = await loadCompanyIndex().catch(() => POPULAR_COMPANIES);
      } finally {
        waitingForIndex.current = false;
        setIsSubmitting(false);
      }
    }
    const pick = pickSubmission(text, index, highlight, recentCompanies);
    if (!pick) {
      // Neither a listed company nor shaped like a US ticker: no request.
      if (text.trim()) setError("Select a listed company or enter a valid US ticker.");
      return;
    }
    launchReport(pick.ticker, pick.name, "full", e);
  };

  const handleSelectCompany = (company, event) => {
    launchReport(company.ticker, company.name, "full", event);
  };

  const handleKeyDown = (e) => {
    if (!isFocused || filteredCompanies.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      isKeyNav.current = true;
      setHighlightIdx((p) => (p + 1) % filteredCompanies.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      isKeyNav.current = true;
      setHighlightIdx((p) => (p - 1 + filteredCompanies.length) % filteredCompanies.length);
    }
  };

  const showDropdown = isFocused && !isSubmitting;

  return (
    <div ref={containerRef} className="relative w-full">
      {/* The input draws no outline of its own (outline:none below): the field shows the focus ring. */}
      <style>{`.search-bar__field:focus-within { outline: 2px solid rgba(255,255,255,0.55); outline-offset: 2px; }
        .search-bar__field { transition: background-color 0.2s ease, border-color 0.2s ease; }
        .search-bar__field:hover { background-color: rgba(255,255,255,0.07) !important; border-color: rgba(255,255,255,0.18) !important; }
        .search-bar__field .search-input { caret-color: #f4f5f7; }
        .search-bar__field .search-input::placeholder { color: rgba(255,255,255,0.35); }
        @media (hover: none) { .search-bar__kbd { display: none !important; } }`}</style>
      <form onSubmit={handleSubmit}>
        <div
          className="search-bar__field"
          style={{
            display: "flex",
            alignItems: "center",
            gap: "0.85rem",
            padding: "0.95rem 1.25rem",
            background: "rgba(255,255,255,0.05)",
            border: "1px solid rgba(255,255,255,0.12)",
            borderRadius: 12,
            boxShadow: "0 1px 2px rgba(0,0,0,0.12)",
          }}
        >
          {isSubmitting ? (
            <Loader2 size={18} style={{ color: "rgba(255,255,255,0.5)", flexShrink: 0, animation: "spin 1s linear infinite" }} />
          ) : (
            <Search size={18} style={{ color: "rgba(255,255,255,0.5)", flexShrink: 0 }} />
          )}
          <input
            ref={inputRef}
            className="search-input"
            type="text"
            value={query}
            onChange={(e) => { setQuery(e.target.value); setError(null); wantIndex(); }}
            onFocus={() => { setIsFocused(true); wantIndex(); }}
            onKeyDown={handleKeyDown}
            placeholder={animatedPlaceholder}
            disabled={isSubmitting}
            aria-label="Search company by ticker or name"
            aria-keyshortcuts="/"
            autoComplete="off"
            spellCheck={false}
            style={{
              width: "100%",
              minWidth: 0,
              border: "none",
              outline: "none",
              background: "none",
              fontFamily: "'Space Grotesk', sans-serif",
              fontSize: "1rem",
              fontWeight: 400,
              color: "#f4f5f7",
            }}
          />
          {/* Clear is always rendered — space reserved, hidden when query is empty.
              Otherwise the first keystroke would shift the input width. The "/"
              key hint sits in that same reserved slot while the box is empty and
              unfocused, so showing/hiding it never moves anything. */}
          <span style={{ position: "relative", display: "inline-flex", flexShrink: 0 }}>
          {!query && !isFocused && !isSubmitting && (
            <kbd
              className="search-bar__kbd"
              aria-hidden="true"
              title="Press / to search"
              style={{
                position: "absolute",
                top: "50%",
                right: 8,
                transform: "translateY(-50%)",
                minWidth: 20,
                height: 20,
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                padding: "0 5px",
                fontSize: "0.72rem",
                lineHeight: 1,
                color: "rgba(255,255,255,0.55)",
                background: "rgba(255,255,255,0.06)",
                border: "1px solid rgba(255,255,255,0.16)",
                borderRadius: 5,
                pointerEvents: "none",
              }}
            >
              /
            </kbd>
          )}
          <button
            type="button"
            onClick={() => { setQuery(""); inputRef.current?.focus(); }}
            disabled={!query || isSubmitting}
            aria-hidden={!query || isSubmitting}
            aria-label="Clear search"
            tabIndex={(!query || isSubmitting) ? -1 : 0}
            style={{
              fontFamily: "'Space Grotesk', sans-serif",
              fontSize: "0.65rem",
              fontWeight: 500,
              letterSpacing: "0.1em",
              textTransform: "uppercase",
              color: "rgba(255,255,255,0.4)",
              background: "none",
              border: "none",
              cursor: (!query || isSubmitting) ? "default" : "pointer",
              padding: "4px 8px",
              borderRadius: 4,
              flexShrink: 0,
              transition: "opacity 0.2s ease, color 0.15s ease",
              opacity: (query && !isSubmitting) ? 1 : 0,
              pointerEvents: (query && !isSubmitting) ? "auto" : "none",
            }}
            onMouseEnter={(e) => { if (query && !isSubmitting) e.currentTarget.style.color = "rgba(255,255,255,0.75)"; }}
            onMouseLeave={(e) => { e.currentTarget.style.color = "rgba(255,255,255,0.4)"; }}
          >
            Clear
          </button>
          </span>
          {/* Generate is always visible — no focus-driven appearance, so the bar
              never shifts when the user clicks into the input. */}
          <button
            type="submit"
            disabled={isSubmitting || (!query.trim() && highlightIdx < 0)}
            aria-label="Generate research report"
            style={{
              fontFamily: "'Space Grotesk', sans-serif",
              fontSize: "0.65rem",
              fontWeight: 500,
              letterSpacing: "0.15em",
              textTransform: "uppercase",
              background: (isSubmitting || (!query.trim() && highlightIdx < 0)) ? "rgba(255,255,255,0.18)" : "#f4f5f7",
              color: (isSubmitting || (!query.trim() && highlightIdx < 0)) ? "rgba(255,255,255,0.45)" : "#0e1420",
              border: "none",
              padding: "8px 20px",
              minHeight: 44,
              borderRadius: 100,
              cursor: isSubmitting ? "default" : "pointer",
              flexShrink: 0,
              transition: "background 0.2s ease, color 0.2s ease",
            }}
            onMouseEnter={(e) => { if (!isSubmitting && (query.trim() || highlightIdx >= 0)) e.currentTarget.style.background = "#ffffff"; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = (isSubmitting || (!query.trim() && highlightIdx < 0)) ? "rgba(255,255,255,0.18)" : "#f4f5f7"; }}
          >
            Generate
          </button>
        </div>
      </form>

      {/* Error */}
      {error && (
        <p style={{
          marginTop: 8,
          fontFamily: "'Space Grotesk', sans-serif",
          fontSize: "0.75rem",
          color: "#f87171",
        }}>
          {error}
        </p>
      )}

      {/* Dropdown */}
      {showDropdown && (
        <div
          ref={dropdownRef}
          style={{
            position: "absolute",
            top: "100%",
            left: 0,
            right: 0,
            marginTop: 8,
            zIndex: 50,
            background: "#1b2230",
            border: "1px solid rgba(255,255,255,0.12)",
            borderRadius: 12,
            boxShadow: "0 12px 40px rgba(0,0,0,0.45)",
            maxHeight: "min(440px, 52vh)",
            overflowY: "auto",
            overflowX: "hidden",
            overscrollBehavior: "contain",
          }}
        >
          {!query && recentCompanies.length > 0 && (
            <div style={{ padding: "12px 16px 6px", display: "flex", alignItems: "center", gap: 5 }}>
              <Clock size={9} style={{ color: "rgba(255,255,255,0.35)" }} />
              <span style={{
                fontFamily: "'Space Grotesk', sans-serif",
                fontSize: "0.6rem",
                textTransform: "uppercase",
                letterSpacing: "0.25em",
                color: "rgba(255,255,255,0.4)",
                fontWeight: 500,
              }}>
                Recents
              </span>
            </div>
          )}
          {!query && recentCompanies.length === 0 && (
            <div style={{ padding: "12px 16px 6px" }}>
              <span style={{
                fontFamily: "'Space Grotesk', sans-serif",
                fontSize: "0.6rem",
                textTransform: "uppercase",
                letterSpacing: "0.25em",
                color: "rgba(255,255,255,0.4)",
                fontWeight: 500,
              }}>
                Popular
              </span>
            </div>
          )}

          <div style={{ padding: "4px 0" }}>
            {filteredCompanies.map((company, idx) => (
              <React.Fragment key={company.ticker}>
              {/* Render "Popular" divider after recents section */}
              {!query && recentCompanies.length > 0 && idx === recentCompanies.length && (
                <div style={{ padding: "10px 16px 6px", borderTop: "1px solid rgba(255,255,255,0.1)", marginTop: 4 }}>
                  <span style={{
                    fontFamily: "'Space Grotesk', sans-serif",
                    fontSize: "0.6rem",
                    textTransform: "uppercase",
                    letterSpacing: "0.25em",
                    color: "rgba(255,255,255,0.4)",
                    fontWeight: 500,
                  }}>
                    Popular
                  </span>
                </div>
              )}
              <button
                type="button"
                ref={(el) => {
                  if (highlightIdx === idx && el && isKeyNav.current) {
                    isKeyNav.current = false;
                    const dd = dropdownRef.current;
                    if (dd) {
                      const et = el.offsetTop;
                      const eb = et + el.offsetHeight;
                      if (et < dd.scrollTop) dd.scrollTo({ top: et, behavior: "smooth" });
                      else if (eb > dd.scrollTop + dd.clientHeight) dd.scrollTo({ top: eb - dd.clientHeight, behavior: "smooth" });
                    }
                  }
                }}
                onClick={(e) => handleSelectCompany(company, e)}
                onMouseEnter={() => { isKeyNav.current = false; setHighlightIdx(idx); }}
                style={{
                  width: "100%",
                  textAlign: "left",
                  border: "none",
                  background: highlightIdx === idx ? "rgba(255,255,255,0.06)" : "none",
                  cursor: "pointer",
                  padding: "10px 16px",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  transition: "background 0.1s ease",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                  <div
                    style={{
                      width: 32,
                      height: 32,
                      borderRadius: 7,
                      background: highlightIdx === idx ? "rgba(255,255,255,0.1)" : "rgba(255,255,255,0.05)",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      transition: "background 0.1s ease",
                    }}
                  >
                    <Building2 size={14} style={{ color: "rgba(255,255,255,0.45)" }} />
                  </div>
                  <div>
                    <span style={{
                      fontFamily: "'Space Grotesk', sans-serif",
                      fontWeight: 500,
                      color: "#f4f5f7",
                      fontSize: "0.85rem",
                      display: "block",
                    }}>
                      {company.adHoc ? `Generate a report for ${company.ticker}` : displayCompanyName(company.name)}
                    </span>
                    <span style={{
                      fontFamily: "'Space Grotesk', sans-serif",
                      fontSize: "0.7rem",
                      color: "rgba(255,255,255,0.7)",
                      fontWeight: 500,
                      letterSpacing: "0.05em",
                    }}>
                      {company.adHoc ? "US ticker · name from its SEC filings" : company.ticker}
                    </span>
                    {company.name_jp && (
                      <span data-testid="search-company-name-jp" lang="ja" style={{
                        fontSize: "0.72rem",
                        color: "rgba(255,255,255,0.5)",
                        marginLeft: 8,
                      }}>
                        {company.name_jp}
                      </span>
                    )}
                  </div>
                </div>
                <ArrowRight
                  size={14}
                  style={{
                    color: "#f4f5f7",
                    opacity: highlightIdx === idx ? 0.45 : 0,
                    transform: highlightIdx === idx ? "translateX(0)" : "translateX(-3px)",
                    transition: "all 0.12s ease",
                  }}
                />
              </button>
              </React.Fragment>
            ))}
          </div>

          {query && !companyIndex && (
            <div style={{ padding: "1.5rem", textAlign: "center" }}>
              <p style={{ fontFamily: "'Space Grotesk', sans-serif", color: "rgba(255,255,255,0.35)", fontSize: "0.85rem" }}>
                Loading companies…
              </p>
            </div>
          )}
          {query && companyIndex && filteredCompanies.length === 0 && (
            <div style={{ padding: "2.5rem", textAlign: "center" }}>
              <Search size={20} style={{ color: "rgba(255,255,255,0.18)", margin: "0 auto 12px", display: "block" }} />
              <p style={{ fontFamily: "'Space Grotesk', sans-serif", color: "rgba(255,255,255,0.35)", fontSize: "0.85rem" }}>
                No results for &quot;{query}&quot;
              </p>
              <p style={{ fontFamily: "'Space Grotesk', sans-serif", color: "rgba(255,255,255,0.3)", fontSize: "0.75rem", marginTop: 4 }}>
                Try a ticker symbol or company name
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

import React, { useState, useEffect, useRef, useMemo, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { safeSameOriginPath } from "@/lib/safeUrl";
import { readReportHistory } from "@/lib/reportStorage";
import { acquireBodyScrollLock } from "@/lib/bodyScrollLock";
import { armedItem, paletteStep } from "@/lib/paletteConfirm";
import { POPULAR_COMPANIES, companyIndexNow, findIndexedTicker, loadCompanyIndex, matchCompanyIndex } from "@/lib/companyIndex";
import { prefetchRoute } from "@/lib/routePrefetch";

/* ── Indago Command Palette (⌘K / Ctrl+K) ────────────────────────────────────
 * A Bloomberg-terminal-style global launcher, mounted once in Layout for every
 * page. PURELY ADDITIVE — it navigates via existing routes and
 * reads existing localStorage; it never mutates app state or touches any page's
 * own logic. Actions:
 *   • jump to Home, Reports or Deep Research
 *   • type a US ticker (e.g. AAPL, any case) → generate a research report for
 *     it. Only a symbol the company list has counts: an ordinary word such as
 *     "home" is shaped like a symbol too, and must never offer a report. That
 *     starts a PAID report, so the first Enter (or click) only arms the row and
 *     asks to confirm; Enter again, or "Generate report", starts it.
 *   • type a company name (apple, micro …) → the matching companies' reports
 *   • reopen a recent report (from per-job history, same Viewer URL Home builds)
 * Fully keyboard-driven (↑↓ Enter Esc), outside-click + Esc close, focus-trapped
 * to the input, respects prefers-reduced-motion, and degrades to nothing if
 * localStorage is blocked. */

const MODULES = [
  { id: "m-home",     label: "Home",     sub: "Start page",                       route: "/Home",         kw: "home start" },
  { id: "m-report",   label: "Reports",  sub: "Generate research reports",        route: "/Reports",      kw: "report research generate reports" },
  { id: "m-deep",     label: "Callisto", sub: "Sourced, verified company research", route: "/DeepResearch", kw: "callisto deep research deepresearch research report analysis" },
];

const ICONS = {
  "m-home":      "M3 11l9-8 9 8 M5 10v10h14V10",
  "m-report":    "M7 3h7l5 5v13H7z M14 3v5h5",
  "m-deep":      "M3 17l6-6 4 4 8-8 M15 7h6v6",
  "action":      "M13 2L3 14h7l-1 8 10-12h-7z",
  "recent":      "M12 8v4l3 3 M21 12a9 9 0 1 1-9-9",
};

// The ticker shortcut follows the Reports search box's rule (findIndexedTicker):
// typed text is a ticker only when it is exactly a symbol the loaded company
// list has (1 to 5 letters, optional class suffix such as BRK.B). Before the
// list arrives the inline Popular companies stand in.

function loadRecents() {
  try {
    return readReportHistory().filter((h) => h && h.jobId && (h.companyName || h.ticker))
      .map((h) => ({ ...h, html: safeSameOriginPath(h.html), pdf: safeSameOriginPath(h.pdf) }))
      .slice(0, 6);
  } catch { return []; }
}

// Mirror Home's inline-view URL construction: same-origin report paths only.
function recentViewerUrl(item) {
  const inline = (u) => { if (!u) return null; if (u.includes("inline=1")) return u; return u.includes("?") ? `${u}&inline=1` : `${u}?inline=1`; };
  const direct = inline(item.html) || inline(item.pdf) || item.html || item.pdf;
  if (!direct) return null;
  const title = item.companyName || item.ticker || "";
  return `/Viewer?${new URLSearchParams({ url: safeSameOriginPath(direct), title, jobId: item.jobId })}`;
}

export default function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const [recents, setRecents] = useState([]);
  const [armedId, setArmedId] = useState(null); // a paid action waiting for its second Enter
  // The Reports search's company list (US symbols and names), loaded the first time the palette opens.
  const [companyIndex, setCompanyIndex] = useState(companyIndexNow);
  const inputRef = useRef(null);
  const listRef = useRef(null);
  const panelRef = useRef(null);
  const returnFocusRef = useRef(null);
  const navigate = useNavigate();

  // global ⌘K / Ctrl+K toggle ("/" is NOT bound here: the Reports search box owns it)
  useEffect(() => {
    const onKey = (e) => {
      const k = e.key.toLowerCase();
      if ((e.metaKey || e.ctrlKey) && k === "k") {
        e.preventDefault();
        setOpen((o) => {
          // The Dashboard menu already owns focus and body-scroll isolation.
          // A portaled route dialog marks #root inert for the same reason. Do
          // not queue the palette invisibly behind either modal: it would be
          // revealed in stale-open state as soon as that modal closes.
          // The third case is any body-portaled aria-modal dialog that does
          // NOT inert #root (a full-screen reader): at the
          // same z-index the later portal paints above, so the palette opened
          // INVISIBLY behind it while still capturing the keyboard — typing +
          // Enter navigated the app under the user with no visible UI
          // (fleet-caught 2026-08-28). Whatever modal is up owns the screen.
          if (!o && (
            // "open" only, NOT "closing": during the menu's 0.6s close leg
            // the palette (z2000) opens cleanly above the animating overlay,
            // and blocking would silently swallow the Cmd+K keystroke
            document.body.getAttribute("data-menu-status") === "open"
            || document.getElementById("root")?.hasAttribute("inert")
            // (:not([aria-hidden]) — the CLOSED Dashboard nav keeps
            // aria-modal while aria-hidden; only a modal actually showing
            // owns the screen)
            || document.querySelector('[aria-modal="true"]:not([aria-hidden="true"]):not([data-command-palette-dialog])')
          )) return false;
          return !o;
        });
      } else if (e.key === "Escape") {
        setOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // on open: reset, focus, and refresh the recents snapshot
  useEffect(() => {
    if (!open) return;
    returnFocusRef.current = document.activeElement;
    setQ(""); setActive(0); setArmedId(null);
    setRecents(loadRecents());
    const t = setTimeout(() => inputRef.current?.focus(), 20);
    return () => clearTimeout(t);
  }, [open]);

  // An aria-modal dialog must also isolate the page behind it.  The focus trap
  // protects keyboard users, while inert/aria-hidden keep background controls
  // out of pointer, keyboard, and assistive-technology navigation.  Preserve
  // any pre-existing state so this composes safely with route-level overlays.
  useEffect(() => {
    if (!open) return;
    // Move focus into the portaled dialog before hiding the trigger's tree.
    // Deferring this until the 20ms polish timer makes Chromium reject the
    // interim aria-hidden mutation because the focused Dashboard button is
    // still its descendant (and emits an accessibility warning).
    try { inputRef.current?.focus({ preventScroll: true }); } catch { /* detached during route change */ }
    const targets = [
      document.querySelector("[data-main]"),
      document.querySelector(".underlay-nav-root"),
      document.querySelector(".indago-wordmark"),
    ].filter(Boolean);
    const prior = targets.map((element) => ({
      element,
      inert: element.hasAttribute("inert"),
      ariaHidden: element.getAttribute("aria-hidden"),
    }));
    for (const { element } of prior) {
      element.setAttribute("inert", "");
      element.setAttribute("aria-hidden", "true");
    }
    const releaseScrollLock = acquireBodyScrollLock();
    return () => {
      releaseScrollLock();
      for (const state of prior) {
        if (!state.inert) state.element.removeAttribute("inert");
        if (state.ariaHidden == null) state.element.removeAttribute("aria-hidden");
        else state.element.setAttribute("aria-hidden", state.ariaHidden);
      }
      // Restore only after every background target is interactive again.
      // Focusing while the trigger is still inert is rejected by browsers and
      // silently strands keyboard users on <body>.
      const priorFocus = returnFocusRef.current;
      returnFocusRef.current = null;
      if (priorFocus instanceof HTMLElement && priorFocus.isConnected) {
        try { priorFocus.focus(); } catch { /* destination may be unmounting */ }
      }
    };
  }, [open]);

  const trapFocus = (e) => {
    if (e.key !== "Tab") return;
    const focusable = [...(panelRef.current?.querySelectorAll(
      'button:not([disabled]), input:not([disabled]), [href], [tabindex]:not([tabindex="-1"])'
    ) || [])];
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  };

  useEffect(() => {
    if (!open || companyIndex) return;
    loadCompanyIndex().then(setCompanyIndex).catch(() => { /* modules, tickers and recents still work */ });
  }, [open, companyIndex]);

  const items = useMemo(() => {
    const query = q.trim();
    const lc = query.toLowerCase();
    const out = [];
    // dynamic actions first (they are what the typed query most likely means)
    const listed = query ? findIndexedTicker(companyIndex || POPULAR_COMPANIES, query) : null;
    if (listed) {
      const t = listed.ticker;
      out.push({ id: "gen-" + t, icon: "action", label: `Generate research report for ${t}`,
                 sub: `${listed.name} · Report mode`, confirm: true, go: () => `/GenerateReport?ticker=${encodeURIComponent(t)}` });
    }
    // companies by name or symbol (apple, micro, brk …); the listed symbol above is not repeated
    if (query && companyIndex) {
      for (const c of matchCompanyIndex(companyIndex, query.toLowerCase(), 5)) {
        if (listed && c.ticker === listed.ticker) continue;
        out.push({ id: "co-" + c.ticker, icon: "action", label: c.name_jp ? `${c.name_jp} · ${c.name}` : c.name,
                   sub: `Generate research report · ${c.ticker}`, confirm: true, go: () => `/GenerateReport?ticker=${encodeURIComponent(c.ticker)}` });
      }
    }
    // modules (fuzzy over label + keywords)
    for (const m of MODULES) {
      if (!lc || m.label.toLowerCase().includes(lc) || m.kw.includes(lc)) {
        out.push({ id: m.id, icon: m.id, label: m.label, sub: m.sub, route: m.route, go: () => m.route });
      }
    }
    // recent reports
    for (const r of recents) {
      const name = r.companyName || r.ticker;
      if (!lc || String(name).toLowerCase().includes(lc) || String(r.ticker || "").toLowerCase().includes(lc)) {
        const url = recentViewerUrl(r);
        if (url) out.push({ id: "rec-" + r.jobId, icon: "recent", label: name,
                            sub: `Recent report${r.ticker ? " · " + r.ticker : ""}`, go: () => url });
      }
    }
    return out;
  }, [q, recents, companyIndex]);

  // keep the active index in range as the list changes
  useEffect(() => { setActive((a) => Math.min(a, Math.max(0, items.length - 1))); }, [items.length]);

  const armed = armedItem(items, armedId);

  const run = useCallback((it) => {
    const step = paletteStep(it, armedId);
    if (step === "none") return;
    if (step === "arm") { setArmedId(it.id); return; }
    setArmedId(null);
    setOpen(false);
    const dest = it.go();
    if (dest) navigate(dest);
  }, [navigate, armedId]);

  const onInputKey = (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setArmedId(null); setActive((a) => Math.min(items.length - 1, a + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setArmedId(null); setActive((a) => Math.max(0, a - 1)); }
    else if (e.key === "Enter") { e.preventDefault(); run(items[active]); }
  };

  // keep the highlighted row in view
  useEffect(() => {
    if (!open) return;
    const el = listRef.current?.querySelector(`[data-idx="${active}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [active, open]);

  // the highlighted module's page code starts loading before Enter (code only, no API)
  const activeRoute = items[active]?.route;
  useEffect(() => { if (open && activeRoute) prefetchRoute(activeRoute); }, [open, activeRoute]);

  if (!open) return null;

  return (
    <div data-command-palette-dialog="" className="cmdk-backdrop" onMouseDown={() => setOpen(false)} onKeyDown={trapFocus} role="dialog" aria-label="Command palette" aria-modal="true">
      <div ref={panelRef} className="cmdk-panel" onMouseDown={(e) => e.stopPropagation()}>
        <div className="cmdk-inputrow">
          <svg className="cmdk-search" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <circle cx="11" cy="11" r="7" /><path d="M21 21l-4.3-4.3" />
          </svg>
          <input ref={inputRef} className="cmdk-input" name="command-palette-search" aria-label="Search commands" placeholder="Jump to a page, a company or a ticker (AAPL)…"
                 value={q} onChange={(e) => { setQ(e.target.value); setActive(0); setArmedId(null); }} onKeyDown={onInputKey} />
          <kbd className="cmdk-esc">esc</kbd>
        </div>
        <div className="cmdk-list" ref={listRef}>
          {items.length === 0 && <div className="cmdk-empty">No matches — try a page name or a US ticker.</div>}
          {items.map((it, i) => (
            <button key={it.id} data-idx={i} className={"cmdk-item" + (i === active ? " cmdk-item--on" : "")}
                    onMouseEnter={() => { if (i !== active) setArmedId(null); setActive(i); }} onClick={() => run(it)}>
              <span className="cmdk-ic">
                <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                  <path d={ICONS[it.icon] || ICONS.action} />
                </svg>
              </span>
              <span className="cmdk-labels"><span className="cmdk-label">{it.label}</span><span className="cmdk-sub">{armed && armed.id === it.id ? "Press Enter again to confirm" : it.sub}</span></span>
              {i === active && <span className="cmdk-enter">↵</span>}
            </button>
          ))}
        </div>
        {armed && (
          <div className="cmdk-confirm" role="group" aria-label="Confirm report">
            <span className="cmdk-confirm-text" role="status">
              This starts a paid report. Press Enter again, or click Generate report.
            </span>
            <span className="cmdk-confirm-actions">
              <button type="button" className="cmdk-btn" onClick={() => setArmedId(null)}>Cancel</button>
              <button type="button" className="cmdk-btn cmdk-btn--go" onClick={() => run(armed)}>Generate report</button>
            </span>
          </div>
        )}
        <div className="cmdk-foot">
          <span><kbd>↑</kbd><kbd>↓</kbd> navigate</span>
          <span><kbd>↵</kbd> open (ticker: twice)</span>
          <span><kbd>⌘</kbd><kbd>K</kbd> toggle</span>
        </div>
      </div>
      <style>{`
        .cmdk-backdrop{position:fixed;inset:0;z-index:2000;background:rgba(4,7,12,.55);-webkit-backdrop-filter:blur(3px);backdrop-filter:blur(3px);display:flex;align-items:flex-start;justify-content:center;padding-top:14vh;animation:cmdkFade .14s ease;}
        .cmdk-panel{width:min(600px,calc(100vw - 32px));max-height:70vh;display:flex;flex-direction:column;background:rgba(20,28,44,.98);border:1px solid rgba(255,255,255,.12);border-radius:16px;box-shadow:0 32px 80px rgba(0,0,0,.5),0 6px 18px rgba(0,0,0,.3);overflow:hidden;animation:cmdkPop .18s cubic-bezier(.2,.9,.3,1.1);}
        .cmdk-inputrow{display:flex;align-items:center;gap:10px;padding:15px 16px;border-bottom:1px solid rgba(255,255,255,.08);}
        .cmdk-search{color:rgba(255,255,255,.5);flex:0 0 auto;}
        .cmdk-input{flex:1;border:none;outline:none;background:none;font-size:16px;color:#f4f5f7;caret-color:#f4f5f7;font-family:inherit;}
        .cmdk-input::placeholder{color:rgba(255,255,255,.38);}
        .cmdk-esc{flex:0 0 auto;font-size:10.5px;color:rgba(255,255,255,.55);background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.14);border-radius:5px;padding:2px 6px;font-family:inherit;}
        .cmdk-list{overflow-y:auto;padding:6px;}
        .cmdk-empty{padding:26px 14px;text-align:center;color:rgba(255,255,255,.5);font-size:13.5px;}
        .cmdk-item{display:flex;align-items:center;gap:12px;width:100%;text-align:left;background:none;border:none;border-radius:10px;padding:10px 12px;cursor:pointer;font-family:inherit;}
        .cmdk-item--on{background:rgba(255,255,255,.08);}
        .cmdk-ic{flex:0 0 auto;width:30px;height:30px;border-radius:8px;display:flex;align-items:center;justify-content:center;background:rgba(255,255,255,.07);color:#f4f5f7;}
        .cmdk-item--on .cmdk-ic{background:rgba(255,255,255,.14);}
        .cmdk-labels{flex:1;min-width:0;display:flex;flex-direction:column;gap:1px;}
        .cmdk-label{font-size:14px;font-weight:600;color:#f4f5f7;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
        .cmdk-sub{font-size:11.5px;color:rgba(255,255,255,.5);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
        .cmdk-enter{flex:0 0 auto;color:rgba(255,255,255,.7);font-size:14px;}
        .cmdk-confirm{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:8px 12px;padding:10px 16px;border-top:1px solid rgba(255,255,255,.08);background:rgba(251,191,36,.08);font-size:12.5px;color:rgba(255,255,255,.78);}
        .cmdk-confirm-actions{display:flex;gap:8px;}
        .cmdk-btn{min-height:32px;padding:5px 12px;border:1px solid rgba(255,255,255,.2);border-radius:8px;background:transparent;color:#f4f5f7;font:inherit;font-size:12.5px;cursor:pointer;}
        .cmdk-btn:hover{border-color:rgba(255,255,255,.45);}
        .cmdk-btn--go{border-color:#f4f5f7;background:#f4f5f7;color:#0e1420;}
        .cmdk-btn--go:hover{background:#fff;border-color:#fff;}
        .cmdk-foot{display:flex;gap:16px;padding:9px 16px;border-top:1px solid rgba(255,255,255,.08);font-size:11px;color:rgba(255,255,255,.5);}
        .cmdk-foot kbd{font-family:inherit;background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.14);border-radius:4px;padding:1px 5px;margin-right:2px;}
        @keyframes cmdkFade{from{opacity:0;}to{opacity:1;}}
        @keyframes cmdkPop{from{opacity:0;transform:translateY(-8px) scale(.98);}to{opacity:1;transform:none;}}
        @media (prefers-reduced-motion:reduce){.cmdk-backdrop,.cmdk-panel{animation:none;}}
        @media (max-width:760px){.cmdk-backdrop{padding-top:8vh;}.cmdk-foot{display:none;}}
      `}</style>
    </div>
  );
}

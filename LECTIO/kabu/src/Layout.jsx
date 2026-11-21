import StockFinder from "@/components/StockFinder";
import React from "react";
import { useLocation } from "react-router-dom";
import UnderlayNav from "@/components/UnderlayNav";
import CommandPalette from "@/components/CommandPalette";
import useIsPhone from "@/lib/useIsPhone";
import MobileGate from "@/components/MobileGate";

/* Phones get a desktop-recommended gate on every dense/interactive surface.
 * The two mobile-ready surfaces, Home (/Home, and its "/" alias) and Deep
 * Research (/DeepResearch), are exempt. The gate renders IN PLACE OF the page, so no
 * heavy page effect or request ever fires on a phone. */
const MOBILE_ALLOWED_PATHS = new Set(["/", "/Home", "/DeepResearch"]);
/* Pages that embed a workspace with its own Dashboard link: the menu opens
 * from that link (postMessage -> UnderlayNav externalTrigger). */
const EMBED_PATHS = new Set(["/DeepResearch"]);
/* React Router matches paths case-insensitively (a typed #/api opens the /API
 * page, #/home the /Home page), so the phone allow-list does too; otherwise a
 * phone shows the desktop gate on a mobile-ready page. */
const MOBILE_ALLOWED_KEYS = new Set([...MOBILE_ALLOWED_PATHS].map((p) => p.toLowerCase()));
const isMobileAllowed = (path) => MOBILE_ALLOWED_KEYS.has(path.toLowerCase());

/* Scroll position of each page, saved when the reader leaves it, so Back
 * returns to the same spot. Per tab (sessionStorage), keyed by path. */
const SCROLL_KEY = "indago-scroll:";
function savedScroll(path) {
  try {
    const y = Number(window.sessionStorage.getItem(SCROLL_KEY + path));
    return Number.isFinite(y) && y > 0 ? y : 0;
  } catch { return 0; }
}
function saveScroll(path, y) {
  try { window.sessionStorage.setItem(SCROLL_KEY + path, String(Math.max(0, Math.round(y)))); } catch { /* memory only: Back starts at the top */ }
}

const USER_SCROLL_EVENTS = ["wheel", "touchstart", "keydown", "mousedown"];

/**
 * Scroll back to `target` once the page has laid out far enough. A returning
 * page (Home) first renders much shorter than when it was left and fills in as
 * its sections load, so one scrollTo lands short and scroll anchoring then
 * pushes the offset further: the target is re-applied on every size change of
 * the page, with anchoring off, until it has held for `settleMs`, the reader
 * scrolls or presses a key, or `timeoutMs` passes. Returns a cancel function.
 */
export function restoreScrollWhenLaidOut(target, { win = window, timeoutMs = 6000, settleMs = 700 } = {}) {
  const doc = win.document;
  const rootEl = doc.documentElement;
  const anchorBefore = rootEl.style.overflowAnchor;
  rootEl.style.overflowAnchor = "none";
  let done = false;
  let settleTimer = 0;
  let observer = null;
  let poll = 0;
  const finish = () => {
    if (done) return;
    done = true;
    observer?.disconnect();
    win.clearInterval(poll);
    win.clearTimeout(deadline);
    win.clearTimeout(settleTimer);
    for (const type of USER_SCROLL_EVENTS) win.removeEventListener(type, finish, true);
    rootEl.style.overflowAnchor = anchorBefore;
  };
  const apply = () => {
    if (done) return;
    if (Math.abs(win.scrollY - target) > 1) win.scrollTo(0, target);
    win.clearTimeout(settleTimer);
    if (Math.abs(win.scrollY - target) <= 1) settleTimer = win.setTimeout(finish, settleMs);
  };
  for (const type of USER_SCROLL_EVENTS) win.addEventListener(type, finish, { capture: true, passive: true });
  const deadline = win.setTimeout(finish, timeoutMs);
  if (typeof win.ResizeObserver === "function") {
    observer = new win.ResizeObserver(apply);
    observer.observe(doc.body);
  } else {
    poll = win.setInterval(apply, 100);
  }
  apply();
  return finish;
}

/* Global chrome — rendered on every route. The Dashboard's GSAP timeline
 * slides the [data-main] wrapper, which lives here so the effect is
 * consistent across every page. */
export default function Layout({ children, currentPageName }) {
  const location = useLocation();
  const isPhone = useIsPhone();
  /* HashRouter has no scroll restoration: a route change kept the previous
     page's scroll offset, so clicking a stock row low on Home opened the
     CompanyProfile mid-page with its hero off-screen (audit-caught
     2026-08-29). Reset to top on FORWARD navigations only. NOTE: this app
     navigates via raw hash anchors, which reach react-router as POP — so
     useNavigationType cannot tell a fresh click from the Back button
     (verified live). Instead a tiny path stack detects the RETURN shape
     (A → B → back to A): a return scrolls back to where A was left (saved
     on leaving it), once A has laid out far enough — the browser's own
     restore ran before the page re-rendered, landed short on a Home that
     first renders ~2,200 px shorter, and scroll anchoring then pushed it
     ~1,200-1,550 px off, so the browser's restore is switched off here.
     Everything else resets. Search-param changes (CompanyProfile tabs)
     deliberately don't reset. */
  const pathStackRef = React.useRef([]);
  // The last scroll offset the reader had on the current page (scroll events
  // only: read when the route changes, before the new page's layout can clamp it).
  const lastScrollRef = React.useRef(0);
  const restoreRef = React.useRef(null);
  React.useEffect(() => {
    try { if ("scrollRestoration" in window.history) window.history.scrollRestoration = "manual"; } catch { /* the default restore stays */ }
    lastScrollRef.current = window.scrollY;
    const onScroll = () => { lastScrollRef.current = window.scrollY; };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      window.removeEventListener("scroll", onScroll);
      restoreRef.current?.();
    };
  }, []);
  React.useLayoutEffect(() => {
    const stack = pathStackRef.current;
    const leaving = stack.length ? stack[stack.length - 1] : null;
    if (leaving && leaving !== location.pathname) saveScroll(leaving, lastScrollRef.current);
    restoreRef.current?.();
    restoreRef.current = null;
    const prevPrev = stack.length >= 2 ? stack[stack.length - 2] : null;
    const isReturn = prevPrev === location.pathname;
    if (isReturn) {
      stack.pop();
      const target = savedScroll(location.pathname);
      if (target > 0) restoreRef.current = restoreScrollWhenLaidOut(target);
      else window.scrollTo(0, 0);
    } else {
      stack.push(location.pathname);
      if (stack.length > 20) stack.shift();
      window.scrollTo(0, 0);
    }
    lastScrollRef.current = window.scrollY;
  }, [location.pathname]);
  /* The global wordmark + Dashboard menu only appears on the "mode-home"
   * surfaces: Home (/Home), the Research Report home (/Reports) and Deep
   * Research (/DeepResearch). /GenerateReport and /Viewer are focused work surfaces
   * that stay uncluttered, so the global chrome is hidden there. (Those pages
   * have their own back/header buttons.) */
  const path = location.pathname || "/";
  // Phone gate: dense/interactive surfaces are replaced by MobileGate on
  // phones. Decided by path so it composes with the chrome rule below (the
  // wordmark + Dashboard toggle stay usable on top of the light gate).
  const mobileGated = isPhone && !isMobileAllowed(path);
  const showGlobalChrome = path === "/Home" || path === "/Reports" || path === "/DeepResearch" || path === "/";

  return (
    <div className="minh-screen-dvh bg-[#0e1420]">
      {showGlobalChrome && (
        <>
          {/* Every page is on the brand navy, so the header (wordmark and toggle)
              takes light ink; the open menu's own rule turns the toggle dark
              over the white panel. */}
          <style>{`body .underlay-nav .underlay-nav__header { color: #fff; }`}</style>

          {/* Dashboard (Osmo Fixed Underlay Navigation): its fixed <header>
              holds the logo and the open/close toggle; its <nav> panel waits
              under [data-main], which slides left to reveal it. Deep Research
              embeds a workspace with its own Dashboard link, so there the
              header stays out of the way and the menu opens on request
              (postMessage -> UnderlayNav externalTrigger). */}
          <UnderlayNav mainSelector="[data-main]" externalTrigger={EMBED_PATHS.has(path)} />
          {/* The stock finder portals into the header's container above (it waits for it). */}
          <StockFinder />
        </>
      )}

      {/* The single [data-main] wrapper (the resource's underlay principle):
          every page renders inside it and the Dashboard's GSAP timeline
          translates it by the menu width (--menu-width) to reveal the menu.
          `position: relative; z-index: 2` stacks it above the fixed z-index 1
          menu panel, and the opaque background keeps the closed menu hidden
          behind pages whose own canvas is transparent. */}
      <div data-main className="minh-screen-dvh" style={{ position: "relative", zIndex: 2, background: "#0e1420" }}>
        {mobileGated ? <MobileGate pageName={currentPageName} /> : children}
      </div>
      {/* Global ⌘K launcher on every page. Additive overlay: it navigates existing routes only. */}
      <CommandPalette />
    </div>
  );
}

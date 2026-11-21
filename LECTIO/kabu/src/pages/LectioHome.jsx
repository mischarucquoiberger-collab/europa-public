import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

const HOME_BG = "#0e1420";
/** The fixed header's area: the page starts the desk below it and the scroll band covers it. */
const HEADER_SPACE = 84;

/** The markets desk, a separate app embedded on Home (markets/: `npm run dev`). */
export const MARKETS_URL = String(import.meta.env?.VITE_MARKETS_URL || "http://127.0.0.1:3015").replace(/\/+$/, "");
/** After the frame's load the desk has this long to post its first height before Home says it is not running. */
export const DESK_ANSWER_MS = 5000;
/** A frame that never loads (a request that hangs) counts as not running after this long. */
export const DESK_LOAD_MS = 20000;
/** While the desk is not running the frame is quietly tried again this often, so the page recovers by itself. */
export const DESK_RETRY_MS = 10000;
/** The frame never collapses below this: a zero-height cross-origin frame stops rendering and would never report again. */
const MIN_FRAME = 240;

/** The desk page a `page=` deep link asks for (#/Home?page=/stocks/NVDA or ?page=/reports…), or "" for
 *  anything else: only a ticker page or the reports page, never another origin or a dot segment.
 *  index.html applies the same test before the first paint to skip the splash for these links. */
export function deskPage(hash) {
  const text = String(hash || "");
  const cut = text.indexOf("?");
  if (cut < 0) return "";
  let page = "";
  try { page = new URLSearchParams(text.slice(cut + 1)).get("page") || ""; } catch { return ""; }
  return /^\/stocks\/[A-Z0-9][A-Z0-9.:%-]*$/i.test(page) || /^\/reports(?:\?|$)/.test(page) ? page : "";
}

function originOf(url) {
  try { return new URL(url).origin; } catch { return ""; }
}

const STATUS_CSS = `
.desk-status{position:absolute;left:0;right:0;top:${HEADER_SPACE}px;height:calc(100vh - ${HEADER_SPACE}px);z-index:1;
  display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px;padding:0 20px 8vh;
  background:${HOME_BG};color:#dce5ee;font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;text-align:center;}
.desk-status p{margin:0;}
.desk-status__title{font-size:17px;font-weight:600;color:#f2f5f9;}
.desk-status__hint{color:#b3becd;}
.desk-status__hint code{font:13px/1.4 ui-monospace,"SF Mono",Menlo,monospace;color:#dce5ee;background:#182332;border:1px solid #2b3a4e;border-radius:6px;padding:2px 7px;}
.desk-status__retry{margin-top:8px;padding:7px 18px;border:1px solid #404e61;border-radius:8px;background:#182332;color:#e6edf5;font:inherit;cursor:pointer;}
.desk-status__retry:is(:hover,:focus-visible){background:#223044;border-color:#849ab6;}
.desk-status__retry:focus-visible{outline:2px solid #91b5dc;outline-offset:2px;}
.desk-status--loading{color:#8d9aab;}
`;

export default function LectioHome() {
  const marketOrigin = originOf(MARKETS_URL);
  const [marketPath, setMarketPath] = useState(() => (typeof window === "undefined" ? "" : deskPage(window.location.hash)));
  useEffect(() => {
    const syncRoute = () => setMarketPath(deskPage(window.location.hash));
    syncRoute();
    window.addEventListener("hashchange", syncRoute);
    return () => window.removeEventListener("hashchange", syncRoute);
  }, []);
  const src = MARKETS_URL + marketPath;

  /* The desk reports its height; until it does, Home shows a quiet loading line, and when it never
     does (no answer within DESK_ANSWER_MS of the frame's load, or no load within DESK_LOAD_MS) it
     says the desk is not running. `attempt` remounts the frame for Retry. */
  const frame = useRef(null);
  const [height, setHeight] = useState(0);
  const [status, setStatus] = useState("loading");
  const [attempt, setAttempt] = useState(0);
  const heard = useRef(false);
  const watchdog = useRef(0);
  const giveUpAfter = useCallback((ms) => {
    window.clearTimeout(watchdog.current);
    watchdog.current = window.setTimeout(() => { if (!heard.current) setStatus("down"); }, ms);
  }, []);
  useEffect(() => {
    heard.current = false;
    giveUpAfter(DESK_LOAD_MS);
    return () => window.clearTimeout(watchdog.current);
  }, [src, attempt, giveUpAfter]);
  const onFrameLoad = () => { if (!heard.current) giveUpAfter(DESK_ANSWER_MS); };
  useEffect(() => {
    const resize = (event) => {
      if (!marketOrigin || event.origin !== marketOrigin || event.source !== frame.current?.contentWindow) return;
      if (event.data?.type !== "europa-market-height" || !Number.isFinite(event.data.height) || event.data.height <= 0) return;
      heard.current = true;
      window.clearTimeout(watchdog.current);
      setHeight(Math.max(MIN_FRAME, Math.ceil(event.data.height)));
      setStatus("ready");
    };
    window.addEventListener("message", resize);
    return () => window.removeEventListener("message", resize);
  }, [marketOrigin]);
  useEffect(() => {
    if (status !== "down") return undefined;
    const retry = window.setInterval(() => setAttempt((n) => n + 1), DESK_RETRY_MS);
    return () => window.clearInterval(retry);
  }, [status]);
  const retryNow = () => { setStatus("loading"); setAttempt((n) => n + 1); };

  // The dark-page contract the dashboard used: page ink behind everything (no
  // white overscroll band) and body[data-home-dark], which gives the fixed
  // header its light ink. --home-logo-backdrop (0 to 1 over the first 84 px of
  // scroll) fades in the blurred band behind the header.
  useEffect(() => {
    const de = document.documentElement;
    const b = document.body;
    const prevHtmlBg = de.style.background;
    const prevBodyBg = b.style.background;
    const prevScheme = de.style.colorScheme;
    de.style.background = HOME_BG;
    b.style.background = HOME_BG;
    de.style.colorScheme = "dark";
    b.setAttribute("data-home-dark", "1");
    let previousOpacity;
    const updateBackdrop = () => {
      const opacity = Math.min(1, Math.max(0, window.scrollY / HEADER_SPACE));
      if (opacity !== previousOpacity) {
        b.style.setProperty("--home-logo-backdrop", String(opacity));
        previousOpacity = opacity;
      }
    };
    updateBackdrop();
    window.addEventListener("scroll", updateBackdrop, { passive: true });
    return () => {
      window.removeEventListener("scroll", updateBackdrop);
      b.style.removeProperty("--home-logo-backdrop");
      de.style.background = prevHtmlBg;
      b.style.background = prevBodyBg;
      de.style.colorScheme = prevScheme;
      b.removeAttribute("data-home-dark");
    };
  }, []);

  const ready = status === "ready";
  return (
    <main style={{ position: "relative", background: HOME_BG, paddingTop: HEADER_SPACE }}>
      <style>{STATUS_CSS}</style>
      {/* The frame stays in place (and visible to the browser) while it loads, so the desk keeps rendering and can report. */}
      <iframe key={attempt} title="Europa markets" src={src} ref={frame} onLoad={onFrameLoad}
        style={{ display: "block", width: "100%", border: 0, background: HOME_BG,
          height: ready ? height : `calc(100vh - ${HEADER_SPACE}px)` }} />
      {status === "down" ? (
        <div className="desk-status" role="alert">
          <p className="desk-status__title">The markets desk is not running.</p>
          <p className="desk-status__hint">In the markets folder: <code>npm run dev</code></p>
          <button type="button" className="desk-status__retry" onClick={retryNow}>Retry</button>
        </div>
      ) : !ready ? (
        <div className="desk-status desk-status--loading" role="status">
          <p>Loading the markets desk…</p>
        </div>
      ) : null}
      {typeof document !== "undefined" && document.body
        ? createPortal(<div className="home-top-blur" aria-hidden="true" />, document.body)
        : null}
    </main>
  );
}

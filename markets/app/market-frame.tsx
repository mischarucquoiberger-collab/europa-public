"use client";
import { useEffect } from "react";
import { usePathname } from "next/navigation";
import { shellUrl } from "@/lib/shell";

/**
 * Origins that may receive the desk's height: the shell's own origin (from
 * NEXT_PUBLIC_EUROPA_URL), plus the referrer's origin when it is some other host
 * framing the desk. The referrer alone is not enough: after a full navigation inside
 * the frame it is the desk itself, and it is empty when the referrer is withheld.
 */
function parentOrigins() {
  const origins = new Set<string>();
  try { origins.add(new URL(shellUrl).origin); } catch {}
  try {
    const referrer = document.referrer ? new URL(document.referrer).origin : "";
    if (referrer && referrer !== window.location.origin) origins.add(referrer);
  } catch {}
  return [...origins];
}

function postHeight() {
  if (window.parent === window) return;
  const height = document.body.offsetHeight;
  if (!height) return;
  for (const origin of parentOrigins()) window.parent.postMessage({ type: "europa-market-height", height }, origin);
}

export default function MarketFrameSize() {
  const pathname = usePathname();

  // Report the height at once on mount and after every route change inside the frame,
  // not only when the ResizeObserver happens to fire: the shell gives up on a silent desk.
  useEffect(() => {
    postHeight();
    const frame = requestAnimationFrame(postHeight);
    return () => cancelAnimationFrame(frame);
  }, [pathname]);

  useEffect(() => {
    if (window.parent === window) {
      const route = window.location.pathname === "/" ? "" : "?page=" + encodeURIComponent(window.location.pathname + window.location.search);
      window.location.replace(shellUrl + "/#/Home" + route);
      return;
    }
    const observer = new ResizeObserver(postHeight);
    observer.observe(document.body);
    const selector = ".news-grid article,.news-section>h2,.saved-watch tbody tr,.returns-chart,.analytics tbody tr,.analytics>.panel-head,.ipo-entry,.earnings tbody tr,.watch-row,.technicals,.chart-stats>div,.lower-heading,.ledger tbody tr";
    const motion = matchMedia("(prefers-reduced-motion: reduce)");
    // This effect runs as soon as the layout hydrates, while streamed parts of the page
    // (the news under <Suspense>) can still be waiting to hydrate. Writing attributes
    // onto those server-rendered elements made React report a hydration mismatch
    // ("data-on-screen" was on the DOM but not in React's props). So the reveal state
    // lives here, off the DOM, and the only attribute written goes on the comparison
    // chart, which is never server-rendered (it appears only once prices load in the browser).
    const onScreen = new WeakSet<Element>();
    const reveals = new IntersectionObserver(entries => {
      let order = 0;
      for (const entry of entries) {
        const element = entry.target as HTMLElement;
        if (element.matches(".returns-chart")) {
          if (entry.isIntersecting && element.dataset.drawn !== "true") element.dataset.drawn = "true";
          continue;
        }
        if (!entry.isIntersecting) { onScreen.delete(element); continue; }
        if (!onScreen.has(element) && !motion.matches) {
          element.animate([
            {opacity:.22, transform:"translateY(24px)", filter:"blur(3px)"},
            {opacity:1, transform:"translateY(0)", filter:"blur(0)"}
          ], {duration:570, delay:Math.min(order++,3)*65, easing:"cubic-bezier(.2,.7,.2,1)", fill:"backwards"});
        }
        onScreen.add(element);
      }
    }, {threshold:0});
    function register(root: Element) {
      if(root.matches(selector)) reveals.observe(root);
      root.querySelectorAll(selector).forEach(el=>reveals.observe(el));
    }
    register(document.body);
    const additions = new MutationObserver(records => {
      for(const record of records) for(const node of record.addedNodes) if(node instanceof Element) register(node);
    });
    additions.observe(document.body,{subtree:true,childList:true});
    return () => {observer.disconnect(); reveals.disconnect(); additions.disconnect();};
  }, []);
  return null;
}

"use client";
import { useEffect } from "react";

export default function MarketFrameSize() {
  useEffect(() => {
    if (window.parent === window) {
      const shell = process.env.NEXT_PUBLIC_EUROPA_URL || "http://127.0.0.1:5173";
      const route = window.location.pathname === "/" ? "" : "?page=" + encodeURIComponent(window.location.pathname + window.location.search);
      window.location.replace(shell + "/#/Home" + route);
      return;
    }
    if (!document.referrer) return;
    const parentOrigin = new URL(document.referrer).origin;
    const observer = new ResizeObserver(() => {
      window.parent.postMessage({ type: "europa-market-height", height: document.body.offsetHeight }, parentOrigin);
    });
    observer.observe(document.body);
    const selector = ".news-grid article,.news-section>h2,.saved-watch tbody tr,.returns-chart,.analytics tbody tr,.analytics>.panel-head,.ipo-entry,.earnings tbody tr,.watch-row,.technicals,.chart-stats>div,.lower-heading,.ledger tbody tr";
    const motion = matchMedia("(prefers-reduced-motion: reduce)");
    const reveals = new IntersectionObserver(entries => {
      let order = 0;
      for (const entry of entries) {
        const element = entry.target as HTMLElement;
        if (element.matches(".returns-chart") && element.dataset.drawn === "true") continue;
        if (entry.isIntersecting && element.matches(".returns-chart")) element.dataset.drawn = "true";
        if (!entry.isIntersecting) { element.dataset.onScreen = "false"; continue; }
        if (!element.matches(".returns-chart") && element.dataset.onScreen !== "true" && !motion.matches) {
          element.animate([
            {opacity:.22, transform:"translateY(24px)", filter:"blur(3px)"},
            {opacity:1, transform:"translateY(0)", filter:"blur(0)"}
          ], {duration:570, delay:Math.min(order++,3)*65, easing:"cubic-bezier(.2,.7,.2,1)", fill:"backwards"});
        }
        element.dataset.onScreen = "true";
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

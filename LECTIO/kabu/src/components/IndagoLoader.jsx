/* IndagoLoader — the ONE loading visual for the whole portal.

   Used wherever the app waits, so the entry feels like a single continuous moment:
   • App.jsx route loading (a page's code is still on its way)

   Anatomy: the wordmark, a thin track with a bar sweeping back and forth
   (indeterminate — alternate direction, eased at the turnarounds), and a
   short label. Deliberately nothing else — no checklist, no fake percentage
   (owner order 2026-08-20). The wordmark is the header's lettering at the
   header's size, so the loader and the page it opens show one and the same mark. Reduced motion: the sweep is
   explicitly parked mid-track — the global 0.01ms-duration rule would
   otherwise strobe an `alternate` animation between its endpoints at frame
   rate. */

import { letteringWord } from "./indagoLettering.js";

const WORDMARK = letteringWord("Europa");

export default function IndagoLoader({ label = "Loading", tone = "light" }) {
  return (
    <div className={`ndg-loader${tone === "dark" ? " is-dark" : ""}`} role="status" aria-live="polite">
      {/* the header's wordmark: EUROPA in the header lettering, at the header's size */}
      <svg className="ndg-loader-word" viewBox={WORDMARK.viewBox} fill="currentColor" stroke="currentColor" strokeWidth="3" strokeLinejoin="round" aria-hidden="true" focusable="false">
        {WORDMARK.paths.map(({ d, dx, stroke, evenodd }, i) => (
          <path key={i} d={d} transform={dx ? `translate(${dx} 0)` : undefined} fillRule={evenodd ? "evenodd" : undefined} fill={stroke ? "none" : undefined} strokeWidth={stroke ? "10.5" : undefined} />
        ))}
      </svg>
      <div className="ndg-loader-track">
        <div className="ndg-loader-bar" />
      </div>
      <div className="ndg-loader-label">{label}</div>
      <style>{`
        .ndg-loader{display:flex;flex-direction:column;align-items:center;gap:0;
          font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
          color:#131722;-webkit-font-smoothing:antialiased;user-select:none;}
        /* one lettering unit = the header's (0.29959px on desktop) */
        .ndg-loader-word{display:block;width:calc(0.29959px * ${WORDMARK.width});
          height:calc(0.29959px * ${WORDMARK.height});overflow:visible;color:#0a0a0a;}
        /* the bar, going back and forth, 18px under the logo */
        .ndg-loader-track{position:relative;width:236px;height:3px;margin-top:18px;
          background:#ececf0;border-radius:2px;overflow:hidden;}
        .ndg-loader-bar{position:absolute;top:0;left:0;width:84px;height:100%;
          background:#0e1420;border-radius:2px;
          animation:ndgSweep 1.05s cubic-bezier(.45,.05,.55,.95) infinite alternate;}
        @keyframes ndgSweep{from{transform:translateX(0)}to{transform:translateX(152px)}}
        .ndg-loader-label{margin-top:16px;font-size:12.5px;font-weight:600;color:#6a6d78;
          letter-spacing:.01em;}
        /* dark: the Home route, so its dark page is not preceded by a white flash */
        .ndg-loader.is-dark{color:#e8e8ea;}
        .ndg-loader.is-dark .ndg-loader-word{color:#f4f4f5;}
        .ndg-loader.is-dark .ndg-loader-track{background:#1f2738;}
        .ndg-loader.is-dark .ndg-loader-bar{background:#f4f4f5;}
        .ndg-loader.is-dark .ndg-loader-label{color:#8d909a;}
        @media (prefers-reduced-motion: reduce){
          .ndg-loader-bar{animation:none;transform:translateX(76px);}
        }
      `}</style>
    </div>
  );
}

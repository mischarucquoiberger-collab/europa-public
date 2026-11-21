import { useEffect, useRef, useState } from "react";
import gsap from "gsap";
import { CustomEase } from "gsap/CustomEase";
import { SplitText } from "gsap/SplitText";
import { letteringWord } from "./indagoLettering.js";

/* The splash. Osmo Supply's "Logo Reveal Loader" (markup, CSS and timeline as supplied in the
   owner's splash page), with the company name in the header's lettering and the owner's two
   lines of text. It plays over the app on every page load and reload and lifts straight onto the
   page beneath: there is no button before it and no page between it and the app (owner 2026-11-22:
   "only the splash, nothing else"; "after this it goes directly to the app"). The one exception is
   a deep link into the markets desk (#/Home?page=/stocks/… or ?page=/reports…, a chart or brief
   opened in a new tab), which opens on its page at once. index.html makes that decision before
   the first paint (html.splash or not) and this component follows the class it set, so the two
   always agree; nothing is kept in storage between loads. */

export const SPLASH_LINES = Object.freeze(["Searching for life", "Finding financial life"]);
export const SPLASH_EASE = "0.65, 0.01, 0.05, 0.99";

const WORD = letteringWord("Europa");

// Once per page load: a reload plays it again, a route change inside the app never does.
let played = false;

/** Whether this load plays the splash: index.html set html.splash before the first paint (every
 *  load except a desk deep link), and the splash plays once per load. */
function splashDue() {
  return !played && document.documentElement.classList.contains("splash");
}

/** index.html paints the splash ground before any script runs (html.splash); the app's own
 *  ground takes over when the curtain starts to lift, or at once when the splash does not play. */
function releaseGround() {
  document.documentElement.classList.remove("splash");
}

function Wordmark() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="100%"
      viewBox={WORD.viewBox}
      className="loader__logo-img"
      fill="currentColor"
      stroke="currentColor"
      strokeWidth="3"
      strokeLinejoin="round"
      focusable="false"
    >
      {WORD.paths.map(({ d, dx, stroke, evenodd }, i) => (
        <path
          key={i}
          d={d}
          transform={dx ? `translate(${dx} 0)` : undefined}
          fillRule={evenodd ? "evenodd" : undefined}
          fill={stroke ? "none" : undefined}
          strokeWidth={stroke ? "10.5" : undefined}
        />
      ))}
    </svg>
  );
}

export default function EuropaSplash() {
  const wrapRef = useRef(null);
  const [gone, setGone] = useState(() => !splashDue());

  useEffect(() => {
    if (!splashDue()) { releaseGround(); return undefined; }
    played = true;
    const wrap = wrapRef.current;
    if (!wrap || window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      releaseGround();
      setGone(true);
      return undefined;
    }

    // ── Osmo Supply · Logo Reveal Loader (JavaScript as supplied) ──
    gsap.registerPlugin(CustomEase, SplitText);
    CustomEase.create("loader", SPLASH_EASE);

    const container = wrap.querySelector("[data-load-container]");
    const bg = wrap.querySelector("[data-load-bg]");
    const progressBar = wrap.querySelector("[data-load-progress]");
    const logo = wrap.querySelector("[data-load-logo]");
    const textElements = Array.from(wrap.querySelectorAll("[data-load-text]"));

    // Main loader timeline
    const loadTimeline = gsap
      .timeline({
        defaults: {
          ease: "loader",
          duration: 3,
        },
        onComplete: () => setGone(true),
      })
      .set(wrap, { display: "block" })
      .to(progressBar, { scaleX: 1 })
      .to(logo, { clipPath: "inset(0% 0% 0% 0%)" }, "<")
      .to(container, { autoAlpha: 0, duration: 0.5 })
      .to(progressBar, { scaleX: 0, transformOrigin: "right center", duration: 0.5 }, "<")
      .add("hideContent", "<")
      .to(bg, { yPercent: -101, duration: 1 }, "hideContent")
      .set(wrap, { display: "none" });

    // Europa: the app's own ground shows under the lifting curtain
    loadTimeline.call(releaseGround, null, "hideContent");

    // Split the two lines and add them to the load timeline
    const firstWord = new SplitText(textElements[0], { type: "lines,chars", mask: "lines" });
    const secondWord = new SplitText(textElements[1], { type: "lines,chars", mask: "lines" });

    // Set initial states of the text elements and letters
    gsap.set([firstWord.chars, secondWord.chars], { autoAlpha: 0, yPercent: 125 });
    gsap.set(textElements, { autoAlpha: 1 });

    // first text in
    loadTimeline.to(firstWord.chars, { autoAlpha: 1, yPercent: 0, duration: 0.6, stagger: { each: 0.02 } }, 0);
    // first text out while second text in
    loadTimeline.to(firstWord.chars, { autoAlpha: 0, yPercent: -125, duration: 0.4, stagger: { each: 0.02 } }, ">+=0.4");
    loadTimeline.to(secondWord.chars, { autoAlpha: 1, yPercent: 0, duration: 0.6, stagger: { each: 0.02 } }, "<");
    // second text out
    loadTimeline.to(secondWord.chars, { autoAlpha: 0, yPercent: -125, duration: 0.4, stagger: { each: 0.02 } }, "hideContent-=0.5");

    return () => {
      loadTimeline.kill();
      firstWord.revert();
      secondWord.revert();
      releaseGround();
    };
  }, []);

  if (gone) return null;

  return (
    <div ref={wrapRef} data-load-wrap className="europa-splash loader" aria-hidden="true">
      <style>{SPLASH_CSS}</style>
      <div data-load-bg className="loader__bg">
        <div data-load-progress className="loader__bg-bar"></div>
      </div>
      <div data-load-container className="loader__container">
        <div className="loader__logo-wrap">
          <div className="loader__logo-item is--base">
            <Wordmark />
          </div>
          <div data-load-logo className="loader__logo-item is--top">
            <Wordmark />
          </div>
        </div>
        <div className="loader__text-wrap">
          {SPLASH_LINES.map((line) => (
            <span key={line} data-load-text data-load-reset className="loader__text-el">{line}</span>
          ))}
        </div>
      </div>
    </div>
  );
}

/* Osmo Supply · Logo Reveal Loader (CSS as supplied), scoped under .europa-splash, then the
   Europa additions of the owner's page: sizing, the tagline's face and the wider logo slot the
   lettering needs. The layer sits above everything in the app. */
const SPLASH_CSS = `
.europa-splash.loader {
  z-index: 10050;
  color: #fff;
  width: 100%;
  height: 100dvh;
  position: fixed;
  inset: 0% 0% auto;
}

.europa-splash .loader__bg {
  background-color: #0a0a0a;
  width: 100%;
  height: 100%;
  position: absolute;
  inset: 0%;
}

.europa-splash .loader__container {
  z-index: 2;
  flex-flow: column;
  justify-content: center;
  align-items: center;
  width: 100%;
  height: 100%;
  display: flex;
  position: relative;
}

.europa-splash .loader__bg-bar {
  z-index: 1;
  transform-origin: 0%;
  transform-style: preserve-3d;
  background-color: #fff;
  width: 100%;
  height: .5em;
  position: absolute;
  inset: auto 0% 0%;
  transform: scale3d(0, 1, 1);
}

.europa-splash .loader__logo-wrap {
  justify-content: center;
  align-items: center;
  width: 12em;
  height: 3em;
  display: flex;
  position: relative;
}

.europa-splash .loader__logo-item {
  width: 100%;
  position: absolute;
}

.europa-splash .loader__logo-item.is--base {
  opacity: .2;
}

.europa-splash .loader__logo-item.is--top {
  -webkit-clip-path: inset(0% 100% 0% 0%);
  clip-path: inset(0% 100% 0% 0%);
}

.europa-splash .loader__logo-img {
  width: 100%;
  display: block;
}

.europa-splash .loader__text-wrap {
  flex-flow: column;
  justify-content: center;
  align-items: center;
  display: flex;
  position: absolute;
  bottom: 3.5em;
}

.europa-splash .loader__text-el {
  text-transform: uppercase;
  white-space: nowrap;
  margin-bottom: -.25em;
  padding-bottom: .25em;
  font-family: Haffer Mono, Arial, sans-serif;
  position: absolute;
}

.europa-splash [data-load-reset] { opacity: 0; }

/* Europa additions */
.europa-splash.loader { font-size: clamp(16px, 1.7vw, 30px); line-height: 1.2; }
.europa-splash .loader__logo-wrap { width: 16em; }
.europa-splash .loader__logo-img { overflow: visible; }
.europa-splash .loader__text-el { font-family: Haffer Mono, ui-monospace, "SF Mono", Menlo, monospace; font-size: .62em;
  letter-spacing: .34em; padding-left: .34em; color: #fff; }
`;

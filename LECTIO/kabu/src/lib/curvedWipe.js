// Deep Research opening screen, its end (owner 2026-10-13): Osmo Supply's "Curved Wipe Page
// Transition" (https://osmo-curved-wipe-transition.webflow.io/), copied 1:1. The resource's
// runPageLeaveAnimation and runPageEnterAnimation are below character for character
// (tests/fixtures/osmo-curved-wipe.js), with the parts of Osmo's page-transition boilerplate they
// rely on (tests/fixtures/osmo-curved-wipe-boilerplate.js): CustomEase "osmo", the reduced-motion
// query and resetPage. tests/drSplashWipe.test.js pins all of it against the fixtures.
//
// Barba is not used here: DrSplash.jsx calls runCurvedWipe(current, next), which does what
// barba's sync transition does (leave and enter started together) and returns the enter Promise.
// The boilerplate's global gsap.defaults({ ease: "osmo", duration: 0.6 }) would change every GSAP
// animation in the app, so runCurvedWipe sets those defaults only while the two functions build
// their timelines (GSAP copies them into each tween as it is created) and then puts the previous
// ones back.
import { gsap } from "gsap";
import { CustomEase } from "gsap/CustomEase";

gsap.registerPlugin(CustomEase);

// The boilerplate's reduced-motion query. Adaptation: guarded, as there is no window when the
// splash is rendered on the server (tests/drSplash.test.js); in a browser it is the same query.
const rmMQ = typeof window !== "undefined" && typeof window.matchMedia === "function"
  ? window.matchMedia("(prefers-reduced-motion: reduce)")
  : null;
let reducedMotion = rmMQ ? rmMQ.matches : false;
rmMQ?.addEventListener?.("change", e => (reducedMotion = e.matches));
rmMQ?.addListener?.(e => (reducedMotion = e.matches)); 

let durationDefault = 0.6;

CustomEase.create("osmo", "0.625, 0.05, 0, 1");

// No Lenis on this screen (resetPage's smooth-scroll branch stays off).
const hasLenis = false;
const lenis = null;

/* The resource's code from here to runCurvedWipe, unchanged (its unused locals included). */
/* eslint-disable unused-imports/no-unused-vars */
function resetPage(container){
  window.scrollTo(0, 0);
  gsap.set(container, { clearProps: "position,top,left,right" });
  
  if(hasLenis){
    lenis.resize();
    lenis.start();    
  }
}

function runPageLeaveAnimation(current, next) {
  const transitionWrap = document.querySelector("[data-transition-wrap]");
  const transitionPanel = transitionWrap.querySelector("[data-transition-panel]");
  const transitionPanelTop = transitionWrap.querySelector("[data-transition-panel-top]");
  const transitionPanelBottom = transitionWrap.querySelector("[data-transition-panel-bottom]");
  const transitionLogo = transitionWrap.querySelector("[data-transition-logo]");
  const transitionLogoPath = transitionWrap.querySelectorAll("path");
  
  const tl = gsap.timeline({
    onComplete: () => { current.remove() }
  });
  
  if (reducedMotion) {
    // Immediate swap behavior if user prefers reduced motion
    return tl.set(current, { autoAlpha: 0 });
  }
  
  tl.set(transitionPanel, {
    autoAlpha: 1
  }, 0);
  
  tl.set(transitionPanelTop, {
    scaleY: 0,
    height: "15vw"
  }, 0);
  
  tl.set(transitionPanelBottom, {
    scaleY: 1,
    height: "20vw"
  }, 0);
  
  tl.set(transitionLogo, {
    autoAlpha: 1
  });
  
  tl.set(transitionLogoPath, {
    yPercent: 105
  });
  
  tl.set(next,{
    autoAlpha: 0
  }, 0);
  
  tl.fromTo(transitionPanel,{
    yPercent: 0
  },{
    yPercent: -100,
    duration: 1,
  }, 0);
  
  tl.fromTo(transitionPanelTop,{
    scaleY: 0
  },{
    scaleY: 1,
    duration: 1,
  }, "<");
  
  tl.fromTo(transitionLogoPath, {
    yPercent: 105
  },{
    yPercent: 0,
    duration: 0.8,
    ease: "expo.out",
    stagger: {
      amount: 0.06
    }
  }, "<+=0.4");
  
  tl.fromTo(current,{
    y: "0vh"
  },{
    y: "-15dvh",
    duration: 1,
  }, 0);
}

function runPageEnterAnimation(next){
  const transitionWrap = document.querySelector("[data-transition-wrap]");
  const transitionPanel = transitionWrap.querySelector("[data-transition-panel]");
  const transitionPanelTop = transitionWrap.querySelector("[data-transition-panel-top]");
  const transitionPanelBottom = transitionWrap.querySelector("[data-transition-panel-bottom]");
  const transitionLogo = transitionWrap.querySelector("[data-transition-logo]");
  const transitionLogoPath = transitionWrap.querySelectorAll("path");
  
  const tl = gsap.timeline();
  
  if (reducedMotion) {
    // Immediate swap behavior if user prefers reduced motion
    tl.set(next, { autoAlpha: 1 });
    tl.add("pageReady")
    tl.call(resetPage, [next], "pageReady");
    return new Promise(resolve => tl.call(resolve, null, "pageReady"));
  }  
  
  tl.add("startEnter", 1.35);
  
  tl.set(next, {
    autoAlpha: 1,
  }, "startEnter");
  
  tl.fromTo(transitionPanel, {
    yPercent: -100,
  },{
    yPercent: -200,
    duration: 1,
    overwrite: "auto",
    immediateRender: false
  }, "startEnter");
  
  tl.fromTo(transitionPanelBottom,{
    scaleY: 1
  },{
    scaleY: 0,
    duration: 1,
  }, "<");
  
  tl.set(transitionPanel, {
    autoAlpha: 0
  }, ">");
  
  tl.to(transitionLogoPath, {
    yPercent: -130,
    duration: 1.2,
    ease: "expo.inOut",
    stagger: {
      amount: -0.06
    }
  }, "startEnter-=0.4");
  
  tl.from(next, {
    y: "25dvh",
    duration: 1,
  }, "startEnter");
  
  tl.add("pageReady");
  tl.call(resetPage, [next], "pageReady");

  return new Promise(resolve => {
    tl.call(resolve, null, "pageReady");
  });
}
/* eslint-enable unused-imports/no-unused-vars */

/** The props the wipe leaves on the next layer: GSAP's (y, autoAlpha) and resetPage's. */
export const NEXT_PROPS = "transform,visibility,opacity,position,top,left,right";

/**
 * The curved wipe from current to next, as barba's sync transition runs it: leave and enter
 * start together. Returns the enter Promise (resolved at "pageReady", 2.35 s in; at once with
 * reduced motion), with revert(): stops the wipe where it is (every tween and call of both
 * timelines, so resolve never runs) and puts back what it set on the page, for an unmount.
 * @param {Element} current
 * @param {Element} next
 * @returns {Promise<void> & { revert: () => void }}
 */
export function runCurvedWipe(current, next) {
  const defaults = gsap.defaults();
  const previous = { ease: defaults.ease, duration: defaults.duration };
  /** @type {Promise<void>} */
  let entered = Promise.resolve();
  gsap.defaults({ ease: "osmo", duration: durationDefault });
  let ctx;
  try {
    ctx = gsap.context(() => {
      runPageLeaveAnimation(current, next);
      entered = runPageEnterAnimation(next);
    });
  } finally {
    gsap.defaults(previous);
  }
  const revert = () => {
    ctx.revert();
    const wrap = document.querySelector("[data-transition-wrap]");
    const parts = wrap ? [...wrap.querySelectorAll("[data-transition-panel], [data-transition-panel-top], [data-transition-panel-bottom], [data-transition-logo], path")] : [];
    gsap.killTweensOf([...parts, current, next]);
    gsap.set(next, { clearProps: "transform,visibility,opacity" });
  };
  return Object.assign(entered, { revert });
}

/** After the wipe: the next layer as it was, with nothing GSAP or resetPage left on it. */
export function settleNext(next) {
  gsap.set(next, { clearProps: NEXT_PROPS });
}

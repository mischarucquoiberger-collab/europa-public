import { useEffect, useState } from "react";

/**
 * useIsPhone — true when the viewport is phone-sized (either orientation),
 * false on tablets and desktops.
 *
 * The signal is the SHORTER viewport side: a phone is < ~640 px on its short
 * edge in BOTH portrait and landscape (portrait ~360–430, landscape height
 * ~390–430), while a tablet's short edge is ≥ 768 and a laptop's is ≥ 700+.
 * This cleanly gates phones in any orientation and lets tablets/laptops
 * through — a plain `max-width` query would wrongly gate a laptop that a user
 * simply narrows, and would let a landscape phone (wide, but short) slip past.
 *
 * Recomputed on resize + orientationchange so a rotate or a window drag flips
 * it live. Every DOM read is guarded: a sandboxed/hidden context can throw or
 * report 0, and the gate must fail OPEN (treat as desktop) rather than trap a
 * real desktop user behind a phone overlay.
 */
export const PHONE_MAX_SHORT_SIDE = 640;
export const PHONE_LANDSCAPE_MAX_WIDTH = 1000;
export const PHONE_MIN_REAL_SIDE = 200;
/* The gate REPLACES the page (an unmount), so a desktop page enters it only
   once a phone size has held this long; leaving the gate is immediate. A
   transient size (window drag, screenshot, print preview) never unmounts. */
export const PHONE_GATE_SETTLE_MS = 400;

/** Resize handling for the gate, free of React: `compute()` reads the rule,
 *  `set(bool)` writes the state. Returns { update, dispose }. */
export function createPhoneGate({ compute, set, setTimer = setTimeout, clearTimer = clearTimeout,
  settleMs = PHONE_GATE_SETTLE_MS }) {
  let timer = 0;
  const cancel = () => { if (timer) { clearTimer(timer); timer = 0; } };
  return {
    update() {
      cancel();
      if (!compute()) { set(false); return; }
      timer = setTimer(() => { timer = 0; if (compute()) set(true); }, settleMs);
    },
    dispose: cancel,
  };
}

/** Pure rule, exported for tests. A phone is:
 *    - a NARROW viewport (width < 640) in any context, or
 *    - a SHORT viewport (height < 640) that is also not wide (< 1000) AND
 *      driven by a coarse primary pointer (touch) — i.e. a phone held
 *      landscape.
 *  Height alone is never enough: a 1366×768 laptop with browser chrome, a
 *  half-height window or a docked DevTools pane is short but is NOT a phone
 *  (review-caught 2026-09-02 — the first cut gated real desktops). */
export function isPhoneSize(w, h, coarsePointer = false) {
  // 0×0 (thumbnailer, detached) → not a phone; never trap on a bogus read.
  if (!w || !h) return false;
  // Nor on a degenerate one: Chromium reports a 1×1 viewport for a moment
  // while it takes a full-page capture, and no phone is under 200 px a side.
  // Gating on it unmounted the open page (the company page lost its header
  // and refetched everything, 2026-10-12).
  if (w < PHONE_MIN_REAL_SIDE || h < PHONE_MIN_REAL_SIDE) return false;
  if (w < PHONE_MAX_SHORT_SIDE) return true;
  return h < PHONE_MAX_SHORT_SIDE && w < PHONE_LANDSCAPE_MAX_WIDTH && !!coarsePointer;
}

function primaryPointerIsCoarse() {
  try {
    return !!(window.matchMedia && window.matchMedia("(pointer: coarse)").matches);
  } catch {
    return false;                 // fail OPEN: an unknown pointer is a desktop
  }
}

function computeIsPhone() {
  try {
    if (typeof window === "undefined") return false;
    return isPhoneSize(window.innerWidth || 0, window.innerHeight || 0,
                       primaryPointerIsCoarse());
  } catch {
    return false;
  }
}

export default function useIsPhone() {
  const [isPhone, setIsPhone] = useState(computeIsPhone);

  useEffect(() => {
    let raf = 0;
    const gate = createPhoneGate({
      compute: computeIsPhone,
      set: (next) => setIsPhone((prev) => (next === prev ? prev : next)),
    });
    const update = () => {
      // coalesce a burst of resize events into one check per frame
      if (raf) return;
      raf = window.requestAnimationFrame(() => {
        raf = 0;
        gate.update();
      });
    };
    try {
      window.addEventListener("resize", update, { passive: true });
      window.addEventListener("orientationchange", update, { passive: true });
    } catch {
      /* environment without addEventListener — the initial state stands */
    }
    // one post-mount reconciliation in case the first paint measured 0×0
    update();
    return () => {
      try {
        window.removeEventListener("resize", update);
        window.removeEventListener("orientationchange", update);
      } catch {
        /* no-op */
      }
      if (raf) window.cancelAnimationFrame(raf);
      gate.dispose();
    };
  }, []);

  return isPhone;
}

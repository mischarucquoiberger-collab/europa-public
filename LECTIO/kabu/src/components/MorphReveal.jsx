import { useLayoutEffect, useRef, useCallback } from "react";

/*
 * MorphReveal — the same liquid blur/scale/opacity morph used in AuthPage's
 * "Welcome → name" transition, packaged as a reusable entrance primitive.
 *
 * Exports:
 *   <MorphFilters />       — renders the shared SVG filter defs once per page
 *   <MorphItem>           — wraps any child and plays the morph-in animation
 *   adaptiveStagger(count) — returns a (index) => delay function that scales
 *                            stagger duration based on the number of items
 *                            so long lists still finish within ~1.8s while
 *                            short lists keep a generous, premium cadence
 */

function easeOutQuint(t) {
  return 1 - Math.pow(1 - t, 5);
}

export function MorphFilters() {
  return (
    <>
      <style>{`
        .morph-grain {
          position: absolute;
          inset: 0;
          pointer-events: none;
          opacity: 0.04;
          mix-blend-mode: multiply;
          z-index: 30;
          background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
          background-size: 220px 220px;
        }
        @media (prefers-reduced-motion: reduce) {
          .morph-grain { display: none; }
        }
      `}</style>
      <svg
        aria-hidden="true"
        style={{
          position: "absolute",
          width: 0,
          height: 0,
          overflow: "hidden",
          pointerEvents: "none",
        }}
      >
        <defs>
          {/*
           * Threshold goo filter: 25× alpha amplification + -9 offset clamps
           * blurred edges into sharp liquid shapes, causing nearby blurred
           * elements to blob into each other before resolving. Identical to
           * the filter used by AuthPage MorphWelcome.
           */}
          <filter id="morph-threshold">
            <feColorMatrix
              in="SourceGraphic"
              type="matrix"
              values="1 0 0 0 0
                      0 1 0 0 0
                      0 0 1 0 0
                      0 0 0 25 -9"
              result="goo"
            />
            <feComposite in="SourceGraphic" in2="goo" operator="atop" />
          </filter>
          {/*
           * Subtle displacement filter used for textured "liquid push" on the
           * hero title. Very small scale so it feels like breath, not warp.
           */}
          <filter id="morph-displace" x="-10%" y="-10%" width="120%" height="120%">
            <feTurbulence
              type="fractalNoise"
              baseFrequency="0.014 0.02"
              numOctaves="2"
              seed="7"
              result="turb"
            />
            <feDisplacementMap
              in="SourceGraphic"
              in2="turb"
              scale="3"
              xChannelSelector="R"
              yChannelSelector="G"
            />
          </filter>
        </defs>
      </svg>
    </>
  );
}

/**
 * MorphItem — wraps children in a div that plays a morph-in animation on mount.
 *
 * Props:
 *   delay       — seconds to wait before starting
 *   duration    — seconds, total animation length (default 1.1)
 *   maxBlur     — starting blur in px (default 22)
 *   yOffset     — starting y-translate in px (default 14)
 *   startScale  — starting scale (default 0.96)
 *   goo         — if true, applies the threshold goo filter while morphing
 *                 (best for bold solid-color elements like hero titles)
 *   displace    — if true, applies displacement warp while morphing
 *   as          — element tag (default "div")
 *   className, style, ...rest — forwarded to the wrapper element
 */
/** @param {React.HTMLAttributes<HTMLElement> & { delay?: number, duration?: number,
 * maxBlur?: number, yOffset?: number, startScale?: number, goo?: boolean,
 * displace?: boolean, as?: React.ElementType }} props */
export function MorphItem({
  delay = 0,
  duration = 1.1,
  maxBlur = 22,
  yOffset = 14,
  startScale = 0.96,
  goo = false,
  displace = false,
  as: Tag = "div",
  className = "",
  style,
  children,
  ...rest
}) {
  const ref = useRef(null);
  // Capture animation params in a ref so the effect fires exactly once on
  // mount. Without this, any prop change (e.g. a hover-triggered re-render,
  // or a sibling being removed which shifts stagger delays) would restart
  // the entrance animation — causing existing elements to "unanimate" and
  // replay their morph, which looks broken.
  const paramsRef = useRef({ delay, duration, maxBlur, yOffset, startScale, goo, displace });
  paramsRef.current = { delay, duration, maxBlur, yOffset, startScale, goo, displace };

  // Ref callback fires SYNCHRONOUSLY when React attaches the DOM element,
  // strictly before any paint and even before useLayoutEffect. Setting the
  // initial invisible state here guarantees the first paint is in the
  // pre-animation state regardless of any timing anomalies in React's
  // concurrent commit phase.
  const setRef = useCallback((el) => {
    ref.current = el;
    if (!el) return;
    // Guard: only set initial state on first attach (not on unmounts)
    if (el.dataset.morphInitialized === "1") return;
    el.dataset.morphInitialized = "1";
    // Respect reduced motion — leave element visible as-is.
    if (
      typeof window !== "undefined" &&
      window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
    ) {
      return;
    }
    const p = paramsRef.current;
    el.style.opacity = "0";
    el.style.filter = buildFilter(p.maxBlur, p.goo, p.displace);
    el.style.transform = `translate3d(0, ${p.yOffset}px, 0) scale(${p.startScale})`;
    el.style.willChange = "opacity, filter, transform";
    el.style.backfaceVisibility = "hidden";
  }, []);

  // useLayoutEffect runs synchronously after DOM commit but BEFORE the
  // browser paints. This prevents the "flash of fully-visible content" that
  // happens with useEffect: without it, the element is painted in its final
  // state for one frame before the initial morph state (opacity 0, blurred)
  // is applied.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;

    // Respect reduced motion — jump straight to final state.
    const prefersReduced =
      typeof window !== "undefined" &&
      window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    if (prefersReduced) {
      el.style.opacity = "1";
      el.style.filter = "";
      el.style.transform = "";
      return;
    }

    // Snapshot params at mount time so the animation is deterministic.
    const {
      delay: d,
      duration: dur,
      maxBlur: mb,
      yOffset: yo,
      startScale: ss,
      goo: g,
      displace: dp,
    } = paramsRef.current;

    // Initial state — set synchronously before the first paint.
    el.style.opacity = "0";
    el.style.filter = buildFilter(mb, g, dp);
    el.style.transform = `translate3d(0, ${yo}px, 0) scale(${ss})`;
    el.style.willChange = "opacity, filter, transform";
    el.style.backfaceVisibility = "hidden";

    let rafId = 0;
    let startTime = 0;
    let started = false;
    const delayMs = d * 1000;
    const durMs = dur * 1000;

    function tick(now) {
      if (!started) {
        started = true;
        startTime = now + delayMs;
      }
      const t = (now - startTime) / durMs;

      if (t < 0) {
        rafId = requestAnimationFrame(tick);
        return;
      }

      if (t >= 1) {
        // Fully clear all animated properties so we don't leave a lingering
        // stacking context (from transform) or will-change promotion — which
        // can interfere with descendants that use position: fixed, or with
        // dropdown portals inside wrapped children like SearchBar.
        el.style.opacity = "";
        el.style.filter = "";
        el.style.transform = "";
        el.style.willChange = "";
        el.style.backfaceVisibility = "";
        return;
      }

      const p = easeOutQuint(t);
      const blur = mb * (1 - p);
      const y = yo * (1 - p);
      const sc = ss + (1 - ss) * p;

      el.style.opacity = String(p);
      el.style.filter = buildFilter(blur, g && p < 0.85, dp && p < 0.9);
      el.style.transform = `translate3d(0, ${y.toFixed(3)}px, 0) scale(${sc.toFixed(4)})`;

      rafId = requestAnimationFrame(tick);
    }

    rafId = requestAnimationFrame(tick);
    return () => {
      if (rafId) cancelAnimationFrame(rafId);
    };
     
  }, []);

  return (
    <Tag ref={setRef} className={className} style={style} {...rest}>
      {children}
    </Tag>
  );
}

function buildFilter(blur, goo, displace) {
  const parts = [];
  if (blur > 0.05) parts.push(`blur(${blur.toFixed(2)}px)`);
  if (goo) parts.push("url(#morph-threshold)");
  if (displace) parts.push("url(#morph-displace)");
  return parts.join(" ");
}

/**
 * adaptiveStagger — returns an (index) => delay function that keeps total
 * entrance time bounded regardless of item count. With 1 item the stagger
 * is 0 (item enters immediately after any base delay); with many items
 * stagger shrinks so the whole cascade finishes within ~maxTotal seconds.
 */
export function adaptiveStagger(count, options = {}) {
  const {
    minStep = 0.03,
    maxStep = 0.085,
    maxTotal = 1.6,
    base = 0,
  } = options;

  if (count <= 1) return () => base;

  const step = Math.max(minStep, Math.min(maxStep, maxTotal / count));
  return (index) => base + index * step;
}

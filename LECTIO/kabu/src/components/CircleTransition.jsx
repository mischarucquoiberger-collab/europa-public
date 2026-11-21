import { createContext, useContext, useState, useRef, useCallback, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { gsap } from "gsap";
import FlowFieldBackground from "@/components/FlowFieldBackground";

const Ctx = createContext(null);

const SWIRL_PATH_D = "m0 0c3.36 0.06 6.6-2.82 7.07-7.07 0.59-4.19-1.79-9.6-7.07-12.93-5.18-3.4-13.27-4.43-21.21-1.21-7.92 3.09-15.48 10.7-18.79 21.21-3.42 10.46-2.3 23.68 4.64 35.36 6.83 11.64 19.57 21.35 35.36 24.64 15.69 3.43 34.14 0.2 49.5-10.5 15.38-10.52 27.21-28.47 30.5-49.5 3.43-20.92-1.92-44.6-16.36-63.64-14.2-19.1-37.37-33.1-63.64-36.36-26.16-3.45-55.05 4.06-77.78 22.22-22.82 17.9-38.98 46.25-42.22 77.78-3.48 31.43 6.2 65.49 28.08 91.92 21.58 26.55 55.16 44.87 91.92 48.08 36.66 3.5 75.94-8.33 106.07-33.93 30.27-25.28 50.74-64.07 53.93-106.07 3.53-41.9-10.46-86.4-39.79-120.21-28.97-33.99-72.97-56.62-120.21-59.79-47.13-3.56-96.85 12.6-134.35 45.65-37.71 32.65-62.51 81.88-65.65 134.35-3.55 52.4 14.72 107.29 51.51 148.49 36.35 41.41 90.75 68.41 148.49 71.51 57.63 3.58 117.75-16.86 162.63-57.37 45.14-40.03 74.29-99.66 77.37-162.63 3.62-62.86-19.02-128.21-63.22-176.78-43.73-48.85-108.57-80.17-176.78-83.22-68.13-3.64-138.65 21.15-190.92 69.08-52.57 47.43-86.06 117.45-89.08 190.92-3.66 73.36 23.29 149.1 74.94 205.06 51.12 56.3 126.35 91.94 205.06 94.94 78.6 3.69 159.56-25.42 219.2-80.8 60.03-54.8 97.82-135.26 100.8-219.2 3.72-83.84-27.56-170.01-86.65-233.35-58.51-63.77-144.14-103.69-233.35-106.65-89.07-3.71-180.46 29.68-247.49 92.51-67.51 62.18-109.54 153.08-112.51 247.49-3.74 94.33 31.82 190.91 98.37 261.63 65.88 71.23 161.96 115.43 261.63 118.37 99.57 3.76 201.36-33.95 275.77-104.23 74.96-69.57 121.31-170.86 124.23-275.77";

export function useCircleTransition() {
  return useContext(Ctx);
}

const EXPAND_MS = 900;
const FADE_MS = 500;
const SWIRL_STROKE_MIN = 100;
const SWIRL_STROKE_MAX = 400;
const SWIRL_COVER_HOLD_MS = 320;

export function CircleTransitionProvider({ children }) {
  const navigate = useNavigate();

  const [ov, setOv] = useState(null);
  // ov = { cx, cy, phase }
  // phases: mount → expand → fade → null

  const targetRef = useRef(null);
  const busyRef = useRef(false);

  const swirlWrapperRef = useRef(null);
  const swirlBackdropRef = useRef(null);
  const swirlPathRef = useRef(null);
  const swirlTlRef = useRef(null);
  const swirlBusyRef = useRef(false);

  const waitForNextPaint = useCallback(
    () =>
      new Promise((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(resolve));
      }),
    []
  );

  const resetSwirlOverlay = useCallback(() => {
    const wrapper = swirlWrapperRef.current;
    const backdrop = swirlBackdropRef.current;
    const path = swirlPathRef.current;
    if (!wrapper || !backdrop || !path) return;

    const pathLength = path.getTotalLength();
    gsap.set(wrapper, {
      autoAlpha: 0,
      visibility: "hidden",
      pointerEvents: "none",
    });
    gsap.set(backdrop, {
      autoAlpha: 0,
      opacity: 0,
    });
    gsap.set(path, {
      opacity: 0,
      strokeDasharray: `${pathLength} ${pathLength}`,
      strokeDashoffset: pathLength,
      attr: { "stroke-width": SWIRL_STROKE_MIN },
    });
  }, []);

  const runSwirlTransition = useCallback(
    /** @param {{ onCovered?: () => void | Promise<void> }} [options] */
    async ({ onCovered } = {}) => {
      if (swirlBusyRef.current) return;

      const wrapper = swirlWrapperRef.current;
      const backdrop = swirlBackdropRef.current;
      const path = swirlPathRef.current;

      if (!wrapper || !backdrop || !path) {
        await Promise.resolve(onCovered?.());
        return;
      }

      swirlBusyRef.current = true;
      swirlTlRef.current?.kill();

      try {
        const pathLength = path.getTotalLength();

        gsap.set(wrapper, {
          autoAlpha: 1,
          visibility: "visible",
          pointerEvents: "auto",
        });
        gsap.set(backdrop, {
          autoAlpha: 1,
          opacity: 0,
        });
        gsap.set(path, {
          opacity: 0,
          strokeDasharray: `${pathLength} ${pathLength}`,
          strokeDashoffset: pathLength,
          attr: { "stroke-width": SWIRL_STROKE_MIN },
        });

        await new Promise((resolve) => {
          const tl = gsap.timeline({
            defaults: { duration: 1.4, ease: "sine.inOut" },
            onComplete: resolve,
          });

          swirlTlRef.current = tl;
          tl.to(path, { opacity: 1, duration: 0.5 }, 0);
          tl.to(path, { strokeDashoffset: 0 }, 0);
          tl.to(
            path,
            { attr: { "stroke-width": SWIRL_STROKE_MAX }, ease: "sine.inOut" },
            0.18
          );
          // Fade the backdrop to fully black in sync with the stroke thickening
          // so the cover moment is guaranteed to be all black across the full
          // viewport, regardless of corner gaps left by the spiral disc.
          tl.to(
            backdrop,
            { opacity: 1, duration: 0.9, ease: "sine.inOut" },
            0.6
          );
        });

        // Guarantee a fully opaque black frame before revealing the new page.
        gsap.set(backdrop, {
          autoAlpha: 1,
          opacity: 1,
        });
        await Promise.resolve(onCovered?.());
        await waitForNextPaint();
        await new Promise((resolve) => setTimeout(resolve, SWIRL_COVER_HOLD_MS));

        await new Promise((resolve) => {
          const tl = gsap.timeline({
            defaults: { duration: 1, ease: "sine.inOut" },
            onComplete: resolve,
          });

          swirlTlRef.current = tl;
          // Fade the backdrop out in sync with the stroke thinning so the
          // destination page bleeds through the unwinding spiral rather than
          // popping in all at once.
          tl.to(backdrop, { opacity: 0, duration: 0.5, ease: "sine.inOut" }, 0);
          tl.to(path, { attr: { "stroke-width": SWIRL_STROKE_MIN } }, 0);
          tl.to(path, { strokeDashoffset: -pathLength }, 0.45);
        });
      } finally {
        swirlTlRef.current?.kill();
        swirlTlRef.current = null;
        resetSwirlOverlay();
        swirlBusyRef.current = false;
      }
    },
    [resetSwirlOverlay, waitForNextPaint]
  );

  /* ── Public API ── */
  const navigateWithReveal = useCallback(
    (urlOrPromise, event, opts) => {
      const animate = opts?.animate === true;

      // No animation — navigate immediately (default)
      if (!animate) {
        if (typeof urlOrPromise === "string") {
          navigate(urlOrPromise);
        } else if (urlOrPromise && typeof urlOrPromise.then === "function") {
          // No target (the caller already showed its own error, e.g. a failed
          // report start resolves null): stay put. navigate(null) would push a
          // duplicate entry for this page with its query dropped (Back x2).
          urlOrPromise.then((url) => { if (url) navigate(url); }).catch(() => {});
        }
        return;
      }

      // Animated stripes transition
      if (busyRef.current || swirlBusyRef.current) {
        if (typeof urlOrPromise === "string") navigate(urlOrPromise);
        return;
      }

      busyRef.current = true;

      if (typeof urlOrPromise === "string") {
        targetRef.current = urlOrPromise;
      } else if (urlOrPromise && typeof urlOrPromise.then === "function") {
        urlOrPromise
          .then((url) => {
            if (!url) { busyRef.current = false; setOv(null); return; }
            targetRef.current = url;
          })
          .catch(() => {
            busyRef.current = false;
            setOv(null);
          });
      }

      let cx = window.innerWidth / 2;
      let cy = window.innerHeight / 2;
      if (event?.clientX && event.clientX > 0) {
        cx = event.clientX;
        cy = event.clientY;
      }

      setOv({ cx, cy, phase: "mount" });
    },
    [navigate]
  );

  /* ── Phase progression ── */
  useEffect(() => {
    if (!ov) return;

    if (ov.phase === "mount") {
      // Double-rAF ensures the DOM has painted at clip-path: circle(0%)
      // before we transition to the expanded state
      const raf = requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          setOv((p) => (p ? { ...p, phase: "expand" } : null));
        });
      });
      return () => cancelAnimationFrame(raf);
    }

    if (ov.phase === "expand") {
      let innerId;
      const id = setTimeout(() => {
        // Navigate to target
        if (targetRef.current) {
          const url = targetRef.current;
          targetRef.current = null;
          navigate(url);
        }
        // Brief delay so new page mounts behind the overlay, then fade
        innerId = setTimeout(() => {
          setOv((p) => (p ? { ...p, phase: "fade" } : null));
        }, 60);
      }, EXPAND_MS + 30);
      return () => { clearTimeout(id); clearTimeout(innerId); };
    }

    if (ov.phase === "fade") {
      const id = setTimeout(() => {
        setOv(null);
        busyRef.current = false;
      }, FADE_MS + 30);
      return () => clearTimeout(id);
    }
  }, [ov?.phase, navigate]);  

  /* ── Safety: 5s hard ceiling ── */
  useEffect(() => {
    if (!ov) return;
    const t = setTimeout(() => {
      if (targetRef.current) {
        navigate(targetRef.current);
        targetRef.current = null;
      }
      setOv(null);
      busyRef.current = false;
    }, 5000);
    return () => clearTimeout(t);
  }, [!!ov, navigate]);  

  useEffect(() => {
    resetSwirlOverlay();
    return () => {
      swirlTlRef.current?.kill();
    };
  }, [resetSwirlOverlay]);

  /* ── Render ── */
  const expanded = ov && (ov.phase === "expand" || ov.phase === "fade");
  const fading = ov?.phase === "fade";

  return (
    <Ctx.Provider value={{ navigateWithReveal, runSwirlTransition }}>
      {children}
      {ov && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 9999,
            background: "#0e1420",
            clipPath: expanded
              ? `circle(150% at ${ov.cx}px ${ov.cy}px)`
              : `circle(0% at ${ov.cx}px ${ov.cy}px)`,
            opacity: fading ? 0 : 1,
            transition: [
              `clip-path ${EXPAND_MS}ms cubic-bezier(0.76, 0, 0.24, 1)`,
              `opacity ${FADE_MS}ms cubic-bezier(0.4, 0, 0.2, 1)`,
            ].join(", "),
            pointerEvents: fading ? "none" : "auto",
            willChange: "clip-path, opacity",
          }}
          aria-hidden="true"
        >
          <FlowFieldBackground />
        </div>
      )}
      <style>{`
        .ct-swirl-overlay {
          position: fixed;
          inset: 0;
          overflow: hidden;
          z-index: 10000;
          visibility: hidden;
          pointer-events: none;
          opacity: 0;
        }
        .ct-swirl-backdrop {
          position: absolute;
          inset: 0;
          background: #0e1420;
          opacity: 0;
          will-change: opacity;
        }
      `}</style>
      <div
        ref={swirlWrapperRef}
        className="ct-swirl-overlay"
        aria-hidden="true"
      >
        <div
          ref={swirlBackdropRef}
          className="ct-swirl-backdrop"
        />
        <div
          style={{
            position: "relative",
            width: "100%",
            height: "100%",
            display: "grid",
            placeItems: "center",
          }}
        >
          {/*
           * Exact 1:1 mirror of SWISS /src/components/TransitionSvgWrapper.astro
           * and /src/styles/app.css .svg__transition svg:
           *     width: 125%;
           *     height: auto;
           *     aspect-ratio: 1;
           *     preserveAspectRatio="xMidYMid slice"
           *
           * The 125% width is deliberate: at that scale the coil spacing
           * (~126 screen px in a 1920-wide viewport) is wider than the
           * starting stroke (100 px), so individual coils are clearly
           * visible as the spiral draws. At a smaller size the stroke
           * width overwhelms the coil spacing and every frame looks like
           * a merged blob. The outer coils clip past the viewport — that
           * IS the SWISS look, and the thickening stroke on top of the
           * backdrop provides full coverage.
           */}
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="-360 -360 760 760"
            preserveAspectRatio="xMidYMid slice"
            style={{
              display: "block",
              width: "125%",
              height: "auto",
              aspectRatio: "1 / 1",
            }}
          >
            <path
              ref={swirlPathRef}
              className="ct-swirl-path"
              d={SWIRL_PATH_D}
              fill="none"
              stroke="#0e1420"
              strokeWidth={SWIRL_STROKE_MIN}
              strokeLinecap="round"
              strokeLinejoin="round"
              vectorEffect="non-scaling-stroke"
              style={{ willChange: "stroke-dashoffset, stroke-width, opacity" }}
            />
          </svg>
        </div>
      </div>
    </Ctx.Provider>
  );
}

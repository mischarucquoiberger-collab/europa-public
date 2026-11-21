import React, { useEffect, useRef, useState } from "react";
import { createAsciiMoon, prepareGlyphTable, prepareTexture } from "./asciiMoon.js";

/* The logo's planet: Europa, spinning, drawn in coloured ASCII (asciiMoon.js),
 * left of the word EUROPA. Decorative: the link's name stays "Europa".
 *
 * Entrance: on the first mount per page load the planet comes up (it rises
 * about 10 px while it fades and scales in, a CSS transition on transform and
 * opacity in UnderlayNav's section 3) together with the glyph arrival. Later
 * mounts (the header unmounts on some pages) show it already arrived.
 * Reduced motion: one still frame, no spin, no entrance. Without WebGL or the
 * texture it renders nothing and reserves no space. */

export const PLANET_TEXTURE_URL = "/europa-tex.png";

/* Set once a renderer has started: no later mount replays the entrance. */
let entrancePlayed = false;

/* The prepared map is kept for the page's lifetime; a failed load is retried on the next mount. */
let texturePromise = null;
function loadPlanetTexture() {
  if (!texturePromise) {
    texturePromise = new Promise((resolve, reject) => {
      const img = new Image();
      img.decoding = "async";
      img.onload = () => {
        try {
          const c = document.createElement("canvas");
          c.width = img.naturalWidth; c.height = img.naturalHeight;
          const x = c.getContext("2d", { willReadFrequently: true });
          if (!x || !c.width) throw new Error("planet texture unreadable");
          x.drawImage(img, 0, 0);
          resolve(prepareTexture(x.getImageData(0, 0, c.width, c.height)));
        } catch (err) { reject(err); }
      };
      img.onerror = () => reject(new Error("planet texture unavailable"));
      img.src = PLANET_TEXTURE_URL;
    });
    texturePromise.catch(() => { texturePromise = null; });
  }
  return texturePromise;
}

function prefersReducedMotion() {
  return typeof window !== "undefined" && Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);
}

export default function LogoPlanet() {
  const spanRef = useRef(/** @type {HTMLSpanElement | null} */ (null));
  const canvasRef = useRef(/** @type {HTMLCanvasElement | null} */ (null));
  // Read once per mount, during the first render: does this mount bring the planet up?
  const [rising] = useState(() => !entrancePlayed);
  const [up, setUp] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    let cancelled = false;
    /** @type {ReturnType<typeof createAsciiMoon>} */
    let moon = null;
    /** @type {MediaQueryList | null} */
    let dprQuery = null;
    const refit = () => moon?.resize();
    // devicePixelRatio changes (zoom, another display): watch the current ratio, re-arm on change
    const onDpr = () => { watchDpr(); refit(); };
    const watchDpr = () => {
      dprQuery?.removeEventListener("change", onDpr);
      dprQuery = window.matchMedia?.(`(resolution: ${window.devicePixelRatio || 1}dppx)`) || null;
      dprQuery?.addEventListener("change", onDpr);
    };
    const sizeObserver = typeof ResizeObserver === "function" ? new ResizeObserver(refit) : null;

    // The renderer is created only after both async loads, so a StrictMode
    // effect replay (cleanup before the loads settle) never takes a context.
    Promise.all([loadPlanetTexture(), prepareGlyphTable()]).then(([texture]) => {
      if (cancelled) return;
      const still = prefersReducedMotion();
      moon = createAsciiMoon(canvas, { texture, arrival: rising && !still, still });
      if (!moon) { setFailed(true); return; }
      entrancePlayed = true;
      // the hidden start state must have been styled for the transition to run
      void spanRef.current?.offsetWidth;
      moon.start();
      setUp(true);
      sizeObserver?.observe(canvas);
      watchDpr();
    }, () => { if (!cancelled) setFailed(true); });

    return () => {
      cancelled = true;
      sizeObserver?.disconnect();
      dprQuery?.removeEventListener("change", onDpr);
      moon?.destroy();
      moon = null;
    };
  }, [rising]);

  if (failed) return null;
  return (
    <span ref={spanRef} className={`underlay-nav__logo-planet${rising && !up ? " is--below" : ""}`} aria-hidden="true">
      <canvas ref={canvasRef} className="underlay-nav__logo-planet-canvas" />
    </span>
  );
}

import { useEffect, useRef } from "react";
import { useLocation } from "react-router-dom";

const ROUTE_TITLES = {
  "/Home": "Home",
  "/Reports": "Research Reports",
  "/GenerateReport": "Generate Report",
  "/Viewer": "Report Viewer",
  "/DeepResearch": "Callisto",
};

// React Router matches paths case-insensitively (#/home opens /Home), so the
// tab title does too.
const TITLE_BY_KEY = new Map(Object.entries(ROUTE_TITLES).map(([path, label]) => [path.toLowerCase(), label]));
export function routeTitle(pathname) {
  return TITLE_BY_KEY.get(String(pathname || "").toLowerCase()) || null;
}

export default function NavigationTracker() {
  const location = useLocation();
  const previousPath = useRef(location.pathname);
  useEffect(() => {
    // "/" and unlisted routes carry the product name alone.
    const label = routeTitle(location.pathname);
    document.title = label ? `${label} · Europa` : "Europa";
    // Do not steal initial focus from purpose-built controls. Focus the new
    // page heading only after navigation.
    if (previousPath.current === location.pathname) return undefined;
    previousPath.current = location.pathname;
    const frame = requestAnimationFrame(() => {
      // Prefer the page heading; several routes render no <h1> (audit P-08),
      // so fall back to the main landmark — silently doing nothing left
      // keyboard/screen-reader focus stranded on the previous page position.
      const target =
        document.querySelector("h1") || document.querySelector("main");
      if (!target) return;
      target.setAttribute("tabindex", "-1");
      target.focus({ preventScroll: true });
    });
    return () => cancelAnimationFrame(frame);
  }, [location.pathname]);
  return null;
}

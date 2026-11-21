import { useEffect } from 'react';
import { Link, useLocation } from 'react-router-dom';

/* An address this app has no page for. The path is shown as the reader typed
 * it (percent-encoding decoded where it is valid, e.g. Japanese text), shortened
 * when very long, and wrapped anywhere, so it never widens the page. */
const MAX_SHOWN = 120;

export function shownPath(pathname) {
  let path = String(pathname || '').replace(/^\/+/, '');
  try { path = decodeURIComponent(path); } catch { /* malformed escapes stay as typed */ }
  // by code point, so a cut never splits an emoji or other surrogate pair
  const chars = Array.from(path);
  return chars.length > MAX_SHOWN ? `${chars.slice(0, MAX_SHOWN - 1).join('')}…` : path;
}

export const NOT_FOUND_TITLE = 'Page not found · Europa';

/** @param {{ serverPath?: string }} [props] */
export default function PageNotFound({ serverPath } = {}) {
  const location = useLocation();
  // An unknown address path (not hash) shows that path; its Home link must
  // leave the path too, or the reload would land here again.
  const path = shownPath(serverPath ?? location.pathname);
  const homeClass = "mt-8 inline-flex items-center rounded-lg bg-[#f4f5f7] px-4 py-2 text-sm font-medium text-[#0e1420] transition-colors hover:bg-white focus:outline-none focus-visible:ring-2 focus-visible:ring-white/70 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0e1420]";

  // Runs after NavigationTracker's route title (it does not know this route is missing).
  useEffect(() => {
    document.title = NOT_FOUND_TITLE;
  }, [location.pathname, serverPath]);

  return (
    <main className="minh-screen-dvh flex items-center justify-center bg-[#0e1420] px-4 py-12 text-[#f4f5f7]">
      <div className="w-full max-w-md min-w-0 text-center">
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-white/60">Error 404</p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight">Page not found</h1>
        <p className="mt-4 text-[15px] leading-relaxed text-white/65 [overflow-wrap:anywhere]">
          {path
            ? <>There is no page at <span className="font-medium text-[#f4f5f7]">“{path}”</span>. Check the address, or go back to Home.</>
            : <>This page does not exist. Check the address, or go back to Home.</>}
        </p>
        {serverPath != null
          ? <a href="/#/Home" className={homeClass}>Go to Home</a>
          : <Link to="/Home" replace className={homeClass}>Go to Home</Link>}
      </div>
    </main>
  );
}

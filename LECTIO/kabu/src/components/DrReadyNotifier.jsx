import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  LIBRARY_API, badgeTitle, messageFor, newTracker, nextDelay, observe, readStored,
  shouldAsk, targetHash, withoutBadge, writeDeclined,
} from '@/lib/drNotify.js';
import './DrReadyNotifier.css';

const supported = () => typeof Notification !== 'undefined';
const permission = () => (supported() ? Notification.permission : 'denied');
function storage() {
  try { return window.localStorage; } catch { return null; }
}

/**
 * Tells the person when Deep Research they started has finished while this tab was
 * hidden: a browser notification ("Research ready: <title>") and a count in the tab
 * title until they come back. Looks at the run listing every 15 s while a run is live
 * (every 45 s otherwise, only while this page is open and visible). Permission is
 * asked in-page, the first time a run starts, never on page load.
 *
 * @param {{ intervals?: { live?: number, idle?: number } }} props (the intervals are for tests)
 */
export default function DrReadyNotifier({ intervals }) {
  const [asking, setAsking] = useState(false);
  const tracker = useRef(newTracker());
  const timer = useRef(0);
  const failures = useRef(0);
  const hiddenIdle = useRef(0);
  const stopped = useRef(false);
  const alive = useRef(true);
  const waiting = useRef(0); // finished runs the person has not seen yet
  const polling = useRef(false);
  const pollRef = useRef(null);
  const prompted = useRef(false);

  const clearBadge = useCallback(() => {
    if (!waiting.current) return;
    waiting.current = 0;
    try { document.title = withoutBadge(document.title); } catch { /* no document */ }
  }, []);

  const announce = useCallback((run) => {
    const message = messageFor(run);
    if (!message) return;
    waiting.current += 1;
    try { document.title = badgeTitle(document.title, waiting.current); } catch { /* no document */ }
    if (permission() !== 'granted') return;
    try {
      const note = new Notification(message.title, { tag: `indago-dr-${run.id}` });
      note.onclick = () => {
        try { window.focus(); } catch { /* ignore */ }
        try { window.location.hash = targetHash(run.thread); } catch { /* ignore */ }
        note.close?.();
      };
    } catch { /* some browsers refuse to construct one outside a service worker */ }
  }, []);

  const schedule = useCallback((anyLive) => {
    clearTimeout(timer.current);
    if (!alive.current || stopped.current) return;
    const hidden = Boolean(document.hidden);
    if (!anyLive && hidden) hiddenIdle.current += 1; else hiddenIdle.current = 0;
    const delay = nextDelay({ anyLive, hidden, hiddenIdle: hiddenIdle.current, failures: failures.current }, intervals);
    if (delay === null) return;
    timer.current = setTimeout(() => pollRef.current?.(), delay);
  }, [intervals]);

  const poll = useCallback(async () => {
    if (polling.current || !alive.current || stopped.current) return;
    polling.current = true;
    let anyLive = Object.keys(tracker.current.live).length > 0;
    try {
      const response = await fetch(LIBRARY_API, { cache: 'no-store' });
      if (response.status === 401 || response.status === 403) { stopped.current = true; return; }
      if (!response.ok) { failures.current += 1; return; }
      const data = await response.json();
      failures.current = 0;
      const seen = observe(tracker.current, data?.items);
      tracker.current = seen.tracker;
      anyLive = seen.anyLive;
      if (!alive.current) return;
      if (seen.started.length && !prompted.current
          && shouldAsk({ supported: supported(), permission: permission(), stored: readStored(storage()) })) {
        prompted.current = true;
        setAsking(true);
      }
      if (document.hidden) for (const run of seen.finished) announce(run);
    } catch {
      failures.current += 1;
    } finally {
      polling.current = false;
      schedule(anyLive);
    }
  }, [announce, schedule]);
  pollRef.current = poll;

  useEffect(() => {
    alive.current = true;
    poll();
    const onVisibility = () => {
      hiddenIdle.current = 0;
      if (!document.hidden) clearBadge();
      clearTimeout(timer.current);
      poll(); // on hide: catch a run that just started; on show: refresh at once
    };
    document.addEventListener('visibilitychange', onVisibility);
    window.addEventListener('focus', clearBadge);
    return () => {
      alive.current = false;
      clearTimeout(timer.current);
      document.removeEventListener('visibilitychange', onVisibility);
      window.removeEventListener('focus', clearBadge);
      clearBadge();
    };
  }, [poll, clearBadge]);

  const accept = async () => {
    setAsking(false);
    try {
      await Notification.requestPermission();
    } catch { /* an old browser's callback form; the choice is the browser's */ }
  };
  const decline = () => {
    setAsking(false);
    writeDeclined(storage());
  };

  if (!asking) return null;
  return (
    <div className="dr-notify" role="region" aria-label="Research notifications">
      <p className="dr-notify__text" role="status">
        Get a notification when this research is ready? It only appears when you are in another tab.
      </p>
      <div className="dr-notify__actions">
        <button type="button" className="dr-notify__button dr-notify__button--primary" onClick={accept}>Notify me</button>
        <button type="button" className="dr-notify__button" onClick={decline}>Not now</button>
      </div>
    </div>
  );
}

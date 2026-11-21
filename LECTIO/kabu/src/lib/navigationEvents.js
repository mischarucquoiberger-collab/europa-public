export const OPEN_INDAGO_NAVIGATION = 'indago:open-navigation';

export function openIndagoNavigation(returnFocus) {
  window.dispatchEvent(new CustomEvent(OPEN_INDAGO_NAVIGATION, { detail: { returnFocus } }));
}

export function isWorkspaceNavigationRequest(event, frame, origin) {
  return Boolean(frame?.contentWindow)
    && event.source === frame.contentWindow
    && event.origin === origin
    && event.data?.type === OPEN_INDAGO_NAVIGATION;
}

/* The menu row that takes focus when the menu opens. Opened from an embedded
   workspace, the host page has seen no pointer, so the browser counts that
   programmatic focus as keyboard focus (:focus-visible) and the menu's
   highlight follows it to the first row ("Home") although the current page is
   another. From a workspace, land on the current page's row instead. */
export function menuEntryFocus(focusables, fromWorkspace) {
  const items = [...(focusables || [])];
  return (fromWorkspace && items.find((el) => el.getAttribute?.('aria-current') === 'page')) || items[0] || null;
}

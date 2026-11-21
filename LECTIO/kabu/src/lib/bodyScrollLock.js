const bodyLockState = new WeakMap();
const appInertState = new WeakMap();
const LOCK_ATTRIBUTE = "data-indago-scroll-lock";

/**
 * Lock body scrolling without letting one overlay release another overlay's
 * lock. The lock lives in an owned data attribute, so inline overflow written
 * by a page or a different overlay is never overwritten or restored stale.
 */
export function acquireBodyScrollLock() {
  if (typeof document === "undefined" || !document.body) return () => {};

  const body = document.body;
  let state = bodyLockState.get(body);
  if (!state) {
    state = {
      owners: 0,
      hadAttribute: body.hasAttribute(LOCK_ATTRIBUTE),
      attributeValue: body.getAttribute(LOCK_ATTRIBUTE),
    };
    bodyLockState.set(body, state);
  }

  state.owners += 1;
  body.setAttribute(LOCK_ATTRIBUTE, "");

  let released = false;
  return () => {
    if (released) return;
    released = true;
    state.owners -= 1;
    if (state.owners > 0) return;

    if (state.hadAttribute) body.setAttribute(LOCK_ATTRIBUTE, state.attributeValue ?? "");
    else body.removeAttribute(LOCK_ATTRIBUTE);
    bodyLockState.delete(body);
  };
}

/**
 * Make the React application root inert while a portaled modal is open.
 * Ownership is reference-counted for the same reason as the body scroll lock:
 * closing one overlay must never reactivate the page underneath another one.
 */
export function acquireAppInertLock() {
  if (typeof document === "undefined") return () => {};

  const root = document.getElementById("root");
  if (!root) return () => {};

  let state = appInertState.get(root);
  if (!state) {
    state = {
      owners: 0,
      hadAttribute: root.hasAttribute("inert"),
      attributeValue: root.getAttribute("inert"),
    };
    appInertState.set(root, state);
  }

  state.owners += 1;
  root.setAttribute("inert", "");

  let released = false;
  return () => {
    if (released) return;
    released = true;
    state.owners -= 1;
    if (state.owners > 0) return;

    if (state.hadAttribute) root.setAttribute("inert", state.attributeValue ?? "");
    else root.removeAttribute("inert");
    appInertState.delete(root);
  };
}

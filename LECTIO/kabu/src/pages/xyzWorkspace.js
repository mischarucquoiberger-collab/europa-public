// A document load alone also succeeds for login pages and proxy errors. Wait
// for LibreChat's real composer without changing its document or application.
export function inspectWorkspaceFrame(frame, expectedOrigin) {
  if (!frame?.contentWindow) return 'loading';
  try {
    const location = frame.contentWindow.location;
    if (location.href === 'about:blank') return 'loading';
    if (location.origin !== expectedOrigin || !location.pathname.startsWith('/xyz/')) {
      return 'unavailable';
    }
    if (/^\/xyz\/(?:login|register|auth|oauth)(?:\/|$)/.test(location.pathname)) {
      return 'auth-error';
    }
    const document = frame.contentDocument;
    if (!document || document.contentType !== 'text/html' || document.querySelector('vite-error-overlay')) {
      return 'unavailable';
    }
    const composer = document.querySelector(
      '#prompt-textarea, textarea[data-testid="text-input"], [data-testid="composer-surface"] [contenteditable="true"][role="textbox"]',
    );
    return composer?.getClientRects().length ? 'ready' : 'loading';
  } catch {
    // Cross-origin redirects and browser error documents cannot be inspected.
    return 'unavailable';
  }
}

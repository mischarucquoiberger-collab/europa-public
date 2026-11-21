/* Server-provided feature switches, read once from the page shell (app/spa_shell.py
   injects <meta name="indago-deep-research" content="off"> when INDAGO_DEEP_RESEARCH=off).
   A missing tag means the feature is on, so a shell without switches changes nothing.
   Hiding here is cosmetic: the server gate is the authority. */
function featureOn(name) {
  try {
    return globalThis.document?.querySelector?.(`meta[name="${name}"]`)?.getAttribute('content') !== 'off';
  } catch {
    return true;
  }
}

export const DEEP_RESEARCH_ENABLED = featureOn('indago-deep-research');
// INDAGO_KEYBOARD_SHORTCUTS=off (app/spa_shell.py) turns the global keyboard layer off for everyone.
export const KEYBOARD_SHORTCUTS_ENABLED = featureOn('indago-shortcuts');

// The command palette's confirm step. Typing a ticker and pressing Enter used to open
// the report page, which starts a paid report at once. An item that starts paid work
// carries `confirm: true`: the first Enter (or click) only arms it, and it runs on the
// second Enter or on the explicit "Generate report" button.

/**
 * What activating `item` does when `armedId` is the item already waiting for confirmation.
 * @returns {'none' | 'arm' | 'run'}
 */
export function paletteStep(item, armedId) {
  if (!item) return 'none';
  if (!item.confirm) return 'run';
  return armedId === item.id ? 'run' : 'arm';
}

/** The armed item, if it is still in the list (a changed query removes it, which disarms). */
export function armedItem(items, armedId) {
  if (!armedId || !Array.isArray(items)) return null;
  return items.find((item) => item.id === armedId && item.confirm) || null;
}

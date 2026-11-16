/**
 * Android back, innermost first. A layer that should close on back (a
 * full-screen photo) registers a handler while it is open; the app's one
 * backButton listener runs the newest handler and goes no further. With no
 * handler, the app's own rule applies (close the holding, else minimise).
 */
const handlers: Array<() => void> = [];

/** Register a back handler; returns the function that removes it. */
export function onBack(fn: () => void): () => void {
  handlers.push(fn);
  return () => {
    const i = handlers.lastIndexOf(fn);
    if (i >= 0) handlers.splice(i, 1);
  };
}

/** Run the newest handler. False when none is registered. */
export function handleBack(): boolean {
  const fn = handlers[handlers.length - 1];
  if (!fn) return false;
  fn();
  return true;
}

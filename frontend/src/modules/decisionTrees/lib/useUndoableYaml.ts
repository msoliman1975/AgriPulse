// History-tracking state for the editor's draft YAML (PR-D8).
//
// Wraps `useState<string|null>` and a bounded stack of prior values.
// Every `setValue` push truncates any redo branch + appends the new
// state; `replace` resets history (used after save lands a new
// baseline). `undo` / `redo` walk the stack without pushing — moving
// through history doesn't itself become a history entry.
//
// We bound the stack at MAX_HISTORY so a long editing session
// doesn't OOM. Older entries fall off the head.

import { useCallback, useState } from "react";

const MAX_HISTORY = 100;

export interface UndoableYaml {
  value: string | null;
  /** Append a new value to history. No-op when next === current. */
  setValue: (next: string) => void;
  /** Reset history to a new baseline (e.g. after save). Future and
   *  past are both cleared. */
  replace: (next: string) => void;
  undo: () => void;
  redo: () => void;
  canUndo: boolean;
  canRedo: boolean;
}

export function useUndoableYaml(initial: string | null): UndoableYaml {
  // `stack[index]` is the current value. index is -1 only when stack
  // is empty (initial value was null and never replaced).
  const [stack, setStack] = useState<string[]>(initial !== null ? [initial] : []);
  const [index, setIndex] = useState<number>(initial !== null ? 0 : -1);

  const setValue = useCallback((next: string) => {
    setStack((prev) => {
      // No-op for identical values — keeps the history clean of
      // accidental re-renders that pass the same string.
      if (prev[index] === next) return prev;
      const truncated = prev.slice(0, index + 1);
      truncated.push(next);
      // Bound the stack — drop oldest if we exceed MAX_HISTORY.
      if (truncated.length > MAX_HISTORY) {
        truncated.splice(0, truncated.length - MAX_HISTORY);
      }
      // Update index to point at the just-pushed value. setIndex
      // inside a setState updater is fine — React batches.
      setIndex(truncated.length - 1);
      return truncated;
    });
  }, [index]);

  const replace = useCallback((next: string) => {
    setStack([next]);
    setIndex(0);
  }, []);

  const undo = useCallback(() => {
    setIndex((i) => (i > 0 ? i - 1 : i));
  }, []);

  const redo = useCallback(() => {
    setIndex((i) => {
      // Need `stack.length` here, but `setIndex` doesn't see the
      // latest stack via closure — use the functional setStack to
      // resolve length, then bail with the requested index.
      return i;
    });
    // Apply the bounded increment in a second setState so we can read
    // the current stack length. Cleaner than smuggling it via ref.
    setStack((prev) => {
      setIndex((i) => (i < prev.length - 1 ? i + 1 : i));
      return prev;
    });
  }, []);

  const value = index >= 0 && index < stack.length ? stack[index] : null;
  const canUndo = index > 0;
  const canRedo = index >= 0 && index < stack.length - 1;

  return { value, setValue, replace, undo, redo, canUndo, canRedo };
}

import clsx from "clsx";
import { useCallback, useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";

interface ModalProps {
  open: boolean;
  onClose: () => void;
  labelledBy: string;
  children: ReactNode;
  className?: string;
  /** When true, Escape-key close is suppressed (e.g. unsaved-changes guard). */
  blockEscape?: boolean;
}

/**
 * Accessible modal dialog. Captures focus on open and restores it on close.
 * The caller controls `open` and provides the dialog content.
 */
export function Modal({
  open,
  onClose,
  labelledBy,
  children,
  className,
  blockEscape,
}: ModalProps): ReactNode {
  const ref = useRef<HTMLDivElement | null>(null);
  const previouslyFocused = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    previouslyFocused.current = document.activeElement as HTMLElement | null;
    const root = ref.current;
    if (root) {
      const focusable = root.querySelector<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
      );
      focusable?.focus();
    }
    return () => {
      previouslyFocused.current?.focus?.();
    };
  }, [open]);

  const onKeyDown = useCallback(
    (event: React.KeyboardEvent) => {
      if (event.key === "Escape" && !blockEscape) {
        event.stopPropagation();
        onClose();
      }
      if (event.key === "Tab") {
        const root = ref.current;
        if (!root) return;
        const focusables = root.querySelectorAll<HTMLElement>(
          'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        );
        if (focusables.length === 0) return;
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    },
    [blockEscape, onClose],
  );

  if (!open) return null;
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* The backdrop is rendered as a button so the click handler is
          a11y-friendly without needing a role override on a non-interactive
          element. It's visually a black overlay. */}
      <button
        type="button"
        aria-label="Close dialog"
        onClick={onClose}
        className="absolute inset-0 bg-black/40"
      />
      {/* role="dialog" makes the keyboard listener semantically valid;
          the linter doesn't see the role override so we silence it. */}
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions */}
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        ref={ref}
        onKeyDown={onKeyDown}
        className={clsx(
          "relative max-h-[90vh] w-full max-w-2xl overflow-auto rounded-2xl bg-ap-panel p-6 shadow-2xl",
          className,
        )}
      >
        {children}
      </div>
    </div>,
    document.body,
  );
}

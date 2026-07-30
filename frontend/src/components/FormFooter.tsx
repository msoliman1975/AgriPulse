import clsx from "clsx";
import type { ReactNode } from "react";

interface FormFooterProps {
  /** Cancel comes first in DOM and visual order — the destructive-adjacent
   *  action should never be the one a fast click lands on. */
  cancel?: ReactNode;
  submit: ReactNode;
  /** Validation summary or server error, shown start-aligned. */
  message?: ReactNode;
  className?: string;
}

export function FormFooter({ cancel, submit, message, className }: FormFooterProps): ReactNode {
  return (
    <div
      className={clsx(
        "flex flex-wrap items-center justify-end gap-3 border-t border-ap-line px-4 py-3",
        className,
      )}
    >
      {message ? <div className="me-auto text-xs text-ap-crit">{message}</div> : null}
      {cancel}
      {submit}
    </div>
  );
}

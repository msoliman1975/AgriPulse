import { useEffect } from "react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

interface Props {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  // Side the drawer slides from in LTR. RTL flips automatically via dir.
  side?: "end" | "start";
}

export function Drawer({ open, onClose, title, children, side = "end" }: Props): ReactNode {
  const { t } = useTranslation("common");

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const sideClass = side === "end" ? "end-0" : "start-0";

  return (
    <div className="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-label={title}>
      <button
        type="button"
        aria-label={t("actions.close")}
        onClick={onClose}
        className="absolute inset-0 bg-slate-900/40"
      />
      <aside
        className={`absolute top-0 ${sideClass} h-full w-full max-w-md overflow-y-auto bg-white shadow-xl`}
      >
        <header className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
          <h2 className="text-lg font-semibold text-slate-800">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("actions.close")}
            className="rounded-md p-1 text-slate-500 hover:bg-slate-100"
          >
            <svg viewBox="0 0 20 20" className="h-5 w-5" aria-hidden="true">
              <path
                fill="currentColor"
                d="M5.3 4.3a1 1 0 0 1 1.4 0L10 7.6l3.3-3.3a1 1 0 1 1 1.4 1.4L11.4 9l3.3 3.3a1 1 0 1 1-1.4 1.4L10 10.4l-3.3 3.3a1 1 0 1 1-1.4-1.4L8.6 9 5.3 5.7a1 1 0 0 1 0-1.4Z"
              />
            </svg>
          </button>
        </header>
        <div className="p-4">{children}</div>
      </aside>
    </div>
  );
}

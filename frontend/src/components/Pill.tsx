import clsx from "clsx";
import type { ReactNode } from "react";

export type PillKind = "ok" | "warn" | "crit" | "neutral" | "info";

interface PillProps {
  kind?: PillKind;
  className?: string;
  children: ReactNode;
}

const KIND_CLASS: Record<PillKind, string> = {
  ok: "bg-ap-primary-soft text-ap-primary",
  warn: "bg-ap-warn-soft text-ap-warn",
  crit: "bg-ap-crit-soft text-ap-crit",
  neutral: "bg-ap-line/70 text-ap-ink",
  info: "bg-blue-50 text-ap-accent",
};

export function Pill({ kind = "neutral", className, children }: PillProps): ReactNode {
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
        KIND_CLASS[kind],
        className,
      )}
    >
      {children}
    </span>
  );
}

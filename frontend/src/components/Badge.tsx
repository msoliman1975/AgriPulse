import clsx from "clsx";
import type { ReactNode } from "react";

export type BadgeKind =
  | "neutral"
  | "type-plant"
  | "type-fert"
  | "type-spray"
  | "type-prune"
  | "type-harv"
  | "type-irrig"
  | "type-soil_prep"
  | "type-observation";

interface BadgeProps {
  kind?: BadgeKind;
  className?: string;
  children: ReactNode;
}

const KIND_CLASS: Record<BadgeKind, string> = {
  neutral: "bg-ap-line/70 text-ap-ink",
  "type-plant": "bg-ap-plant/15 text-ap-plant",
  "type-fert": "bg-ap-fert/15 text-ap-fert",
  "type-spray": "bg-ap-spray/15 text-ap-spray",
  "type-prune": "bg-ap-prune/15 text-ap-prune",
  "type-harv": "bg-ap-harv/15 text-ap-harv",
  "type-irrig": "bg-ap-irrig/15 text-ap-irrig",
  "type-soil_prep": "bg-amber-100 text-amber-800",
  "type-observation": "bg-slate-100 text-slate-700",
};

export function Badge({ kind = "neutral", className, children }: BadgeProps): ReactNode {
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide",
        KIND_CLASS[kind],
        className,
      )}
    >
      {children}
    </span>
  );
}

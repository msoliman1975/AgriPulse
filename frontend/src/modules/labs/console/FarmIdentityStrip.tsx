// "What am I looking at" — the leading slot of the view bar.
//
// The live console answers this only in the app-shell breadcrumb (name and
// tenant), so area and how many units the farm has needed a panel to recall.
//
// Deliberately NOT showing a farm-level crop, even though the reference
// design does: a crop is assigned per block, and there is no farm crop field
// to read. Deriving a "dominant crop" from block assignments would be a guess
// presented as a fact. Crop stays where it is true — the block dock's chips.
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { Block } from "@/api/blocks";
import { AreaDisplay } from "@/modules/farms/components/AreaDisplay";

interface Props {
  name: string;
  areaM2: number | null;
  blocks: readonly Block[];
}

export function FarmIdentityStrip({ name, areaM2, blocks }: Props): ReactNode {
  const { t } = useTranslation("farmConsole");

  const pivots = blocks.filter(
    (b) => b.unit_type === "pivot" || b.unit_type === "pivot_sector",
  ).length;
  const plain = blocks.length - pivots;

  return (
    <div className="flex min-w-0 items-baseline gap-2 border-e border-ap-line pe-3">
      <span className="truncate text-card-title font-bold text-ap-ink" title={name}>
        {name}
      </span>
      <span className="hidden whitespace-nowrap text-meta tabular-nums text-ap-muted sm:inline">
        {areaM2 != null && areaM2 > 0 ? (
          <>
            <AreaDisplay areaM2={areaM2} /> ·{" "}
          </>
        ) : null}
        {t("identity.blocks", { count: plain })}
        {pivots > 0 ? <> · {t("identity.pivots", { count: pivots })}</> : null}
      </span>
    </div>
  );
}

import clsx from "clsx";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { PixelBudget } from "@/api/observer";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { Skeleton } from "@/components/Skeleton";

/**
 * Where a scene's pixels went: AOI footprint → SCL-masked → no-data → valid.
 *
 * This is the answer to "why is valid % 43?", which the database cannot give:
 * it stores the valid and total counts and nothing that separates a
 * cloud-masked pixel from a sensor gap. So the numbers are recomputed from
 * the COG, which is why it is behind a button rather than loaded on open —
 * reading a raster is not something a page visit should do silently.
 */

const ROWS = [
  { key: "aoi", cls: "bg-ap-line" },
  { key: "masked", cls: "bg-ap-warn" },
  { key: "nodata", cls: "bg-ap-crit" },
  { key: "valid", cls: "bg-ap-primary" },
] as const;

export function PixelBudgetCard({
  budget,
  isPending,
  requested,
  onRequest,
  selectedIndex,
}: {
  budget: PixelBudget | undefined;
  isPending: boolean;
  requested: boolean;
  onRequest: () => void;
  selectedIndex: string;
}): ReactNode {
  const { t } = useTranslation("admin");

  if (!requested) {
    return (
      <Card title={t("observer.budget.title")}>
        <p className="mb-3 text-xs text-ap-muted">{t("observer.budget.explain")}</p>
        <Button variant="secondary" onClick={onRequest}>
          {t("observer.budget.compute")}
        </Button>
      </Card>
    );
  }
  if (isPending || !budget) return <Skeleton className="h-56 w-full" />;

  const per = budget.per_index[selectedIndex];
  if (!per) {
    return (
      <Card title={t("observer.budget.title")}>
        <p className="text-xs text-ap-muted">
          {t("observer.budget.noIndex", { index: selectedIndex.toUpperCase() })}
        </p>
      </Card>
    );
  }

  const max = Math.max(1, per.aoi);
  const values: Record<string, number> = {
    aoi: per.aoi,
    masked: per.masked,
    nodata: per.nodata,
    valid: per.valid,
  };

  return (
    <Card
      title={t("observer.budget.title")}
      actions={
        <span className="text-xs text-ap-muted">
          {t("observer.budget.validPct", {
            pct: ((per.valid / max) * 100).toFixed(1),
          })}
        </span>
      }
    >
      <div className="space-y-2">
        {ROWS.map((row) => (
          <div key={row.key} className="grid grid-cols-[9rem_1fr_5rem] items-center gap-3 text-xs">
            <span className={clsx(row.key === "valid" && "font-semibold")}>
              {t(`observer.budget.row.${row.key}`)}
            </span>
            <span className="h-4 overflow-hidden rounded bg-ap-bg">
              <span
                className={clsx("block h-full rounded", row.cls)}
                style={{ width: `${(values[row.key] / max) * 100}%` }}
              />
            </span>
            <span className="text-end font-semibold tabular-nums">
              {row.key === "aoi" || row.key === "valid" ? "" : "−"}
              {values[row.key].toLocaleString()}
            </span>
          </div>
        ))}
      </div>
      <p className="mt-3 border-s-2 border-ap-accent ps-3 text-xs text-ap-muted">
        {t("observer.budget.notStored")}
      </p>
    </Card>
  );
}

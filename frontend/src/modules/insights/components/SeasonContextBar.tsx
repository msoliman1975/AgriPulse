import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { getFarmSeasonContext } from "@/api/insights";
import { Skeleton } from "@/components/Skeleton";

interface Props {
  farmId: string;
}

/**
 * Thin "what's growing here" strip above the trend chart. V1 only
 * shows crop names + per-crop block counts; planting date / phenology
 * / day-of-season is a follow-up that needs reliable activity-type
 * vocab.
 *
 * Empty state ("N blocks, no crops assigned") nudges the operator to
 * seed `block_crops` — without crops, recommendations rules that key
 * off crop won't match anything.
 */
export function SeasonContextBar({ farmId }: Props): ReactNode {
  const { t } = useTranslation("insights");
  const { data, isLoading } = useQuery({
    queryKey: ["insights", "season-context", farmId] as const,
    queryFn: () => getFarmSeasonContext(farmId),
    enabled: Boolean(farmId),
    staleTime: 5 * 60_000,
  });

  if (isLoading) {
    return <Skeleton className="h-10 w-full rounded-md" />;
  }
  if (!data) return null;

  const hasCrops = data.crops.length > 0;
  return (
    <div
      role="region"
      aria-label={t("season.regionLabel")}
      className="flex flex-wrap items-center gap-2 rounded-md border border-ap-line bg-ap-bg/40 px-3 py-2 text-xs"
    >
      <span className="font-semibold text-ap-muted">{t("season.label")}</span>
      {hasCrops ? (
        <div className="flex flex-wrap gap-1.5">
          {data.crops.map((c) => (
            <span
              key={c.crop_id}
              className="inline-flex items-center gap-1 rounded bg-white px-1.5 py-0.5 text-ap-ink shadow-sm"
            >
              <span className="font-medium">{c.name_en}</span>
              <span className="text-[10px] text-ap-muted">
                {t("season.blockCount", { count: c.block_count })}
              </span>
            </span>
          ))}
        </div>
      ) : (
        <span className="text-ap-muted">
          {t("season.noCrops", { count: data.active_block_count })}
        </span>
      )}
    </div>
  );
}

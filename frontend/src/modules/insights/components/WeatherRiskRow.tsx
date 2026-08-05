import { useQuery } from "@tanstack/react-query";
import { useMemo, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { getWeatherRiskSummary, type RiskLevel } from "@/api/weatherRisk";
import { Skeleton } from "@/components/Skeleton";

interface Props {
  farmId: string;
  /** Blocks to count, or null for every block (the crop filter). Risk is the
   *  one weather reading that IS per-block, so it narrows with the crop. */
  blockIds?: readonly string[] | null;
}

const LEVEL_RANK: Record<RiskLevel, number> = { low: 0, moderate: 1, high: 2 };

// Severity tokens (mirror the block health palette: good/warn/crit).
const LEVEL_DOT: Record<RiskLevel, string> = {
  low: "bg-ap-good",
  moderate: "bg-ap-warn",
  high: "bg-ap-crit",
};

/**
 * What the weather is doing TO the crop — the last row of the weather
 * section. Counts blocks at moderate/high weather-driven disease and pest
 * pressure (worst pathogen per block) and links to the map risk overlay.
 *
 * It closes the section deliberately: the rows above are farm-centroid
 * measurements, and this is the one place weather becomes per-block, because
 * risk varies with crop, canopy and growth stage.
 *
 * Gated on `weather_risk.read` by the caller.
 */
export function WeatherRiskRow({ farmId, blockIds = null }: Props): ReactNode {
  const { t } = useTranslation("weatherRisk");

  const summaryQ = useQuery({
    queryKey: ["weatherRisk", "summary", farmId] as const,
    queryFn: () => getWeatherRiskSummary(farmId),
    enabled: Boolean(farmId),
    staleTime: 60_000,
  });

  // Worst level per block, then count those above "low".
  const { atRiskCount, highCount } = useMemo(() => {
    const keep = blockIds ? new Set(blockIds) : null;
    const worst = new Map<string, RiskLevel>();
    for (const r of summaryQ.data?.risks ?? []) {
      if (keep && !keep.has(r.block_id)) continue;
      const cur = worst.get(r.block_id);
      if (cur === undefined || LEVEL_RANK[r.level] > LEVEL_RANK[cur]) {
        worst.set(r.block_id, r.level);
      }
    }
    let atRisk = 0;
    let high = 0;
    for (const level of worst.values()) {
      if (level !== "low") atRisk += 1;
      if (level === "high") high += 1;
    }
    return { atRiskCount: atRisk, highCount: high };
  }, [summaryQ.data, blockIds]);

  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-xs font-bold uppercase tracking-wide text-ap-primary">
          {t("widget.title")}
        </h3>
        <Link to="/labs/map" className="text-xs font-medium text-ap-accent hover:underline">
          {t("widget.viewMap")}
        </Link>
      </div>
      <p className="text-xs text-ap-muted">{t("widget.subtitle")}</p>

      <div className="mt-2">
        {summaryQ.isLoading ? (
          <Skeleton className="h-8 w-40" />
        ) : atRiskCount === 0 ? (
          <p className="text-sm text-ap-muted">{t("widget.none")}</p>
        ) : (
          <div className="flex items-center gap-2">
            <span
              className={`inline-block h-2.5 w-2.5 rounded-full ${highCount > 0 ? LEVEL_DOT.high : LEVEL_DOT.moderate}`}
              aria-hidden
            />
            <span className="text-lg font-semibold text-ap-ink">
              {t("widget.blocksAtRisk", { count: atRiskCount })}
            </span>
            {highCount > 0 ? (
              <span className="rounded-full bg-ap-crit-soft px-2 py-0.5 text-[11px] font-medium text-ap-crit">
                {t("level.high")}: {highCount}
              </span>
            ) : null}
          </div>
        )}
      </div>
    </div>
  );
}

import { useQuery } from "@tanstack/react-query";
import { useMemo, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { getWeatherRiskSummary, type RiskLevel } from "@/api/weatherRisk";
import { Skeleton } from "@/components/Skeleton";

interface Props {
  farmId: string;
}

const _LEVEL_RANK: Record<RiskLevel, number> = { low: 0, moderate: 1, high: 2 };

// Severity tokens (mirror the block health palette: good/warn/crit).
const _LEVEL_DOT: Record<RiskLevel, string> = {
  low: "bg-ap-good",
  moderate: "bg-ap-warn",
  high: "bg-ap-crit",
};

/**
 * Insights "active risks" widget: counts the blocks at moderate/high
 * weather-driven disease/pest pressure (worst pathogen per block) and links
 * to the map risk overlay. Reads the per-block weather-risk summary (PR-R2);
 * gated on `weather_risk.read` by the caller.
 */
export function ActiveRisksWidget({ farmId }: Props): ReactNode {
  const { t } = useTranslation("weatherRisk");

  const summaryQ = useQuery({
    queryKey: ["weatherRisk", "summary", farmId] as const,
    queryFn: () => getWeatherRiskSummary(farmId),
    enabled: Boolean(farmId),
    staleTime: 60_000,
  });

  // Worst level per block, then count those above "low".
  const { atRiskCount, highCount } = useMemo(() => {
    const worst = new Map<string, RiskLevel>();
    for (const r of summaryQ.data?.risks ?? []) {
      const cur = worst.get(r.block_id);
      if (cur === undefined || _LEVEL_RANK[r.level] > _LEVEL_RANK[cur]) {
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
  }, [summaryQ.data]);

  return (
    <section
      aria-labelledby="active-risks-heading"
      className="rounded-xl border border-ap-line bg-ap-panel p-4"
    >
      <header className="flex items-baseline justify-between">
        <div>
          <h2 id="active-risks-heading" className="text-sm font-semibold text-ap-ink">
            {t("widget.title")}
          </h2>
          <p className="text-xs text-ap-muted">{t("widget.subtitle")}</p>
        </div>
        <Link to="/labs/map" className="text-xs font-medium text-ap-accent hover:underline">
          {t("widget.viewMap")}
        </Link>
      </header>

      <div className="mt-3">
        {summaryQ.isLoading ? (
          <Skeleton className="h-8 w-40" />
        ) : atRiskCount === 0 ? (
          <p className="text-sm text-ap-muted">{t("widget.none")}</p>
        ) : (
          <div className="flex items-center gap-2">
            <span
              className={`inline-block h-2.5 w-2.5 rounded-full ${highCount > 0 ? _LEVEL_DOT.high : _LEVEL_DOT.moderate}`}
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
    </section>
  );
}

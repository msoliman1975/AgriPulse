import { useQuery } from "@tanstack/react-query";
import { formatDistanceToNow, parseISO } from "date-fns";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { getFarmHealthSummary, type Health } from "@/api/insights";
import { Skeleton } from "@/components/Skeleton";
import { useDateLocale } from "@/hooks/useDateLocale";

interface Props {
  farmId: string;
}

/**
 * Per-block scorecard: one row per block with health badge, current
 * NDVI value, 30-day trend %, open alert count, and last-observation
 * "X days ago". Backend sort puts critical/watch rows first so the
 * operator's eye lands on attention-worthy blocks.
 *
 * Alert count links to /alerts?block_id=... — keeps this card a
 * read-only summary and the action surface elsewhere.
 */
export function BlockHealthScorecard({ farmId }: Props): ReactNode {
  const { t } = useTranslation("insights");
  const dateLocale = useDateLocale();
  const { data, isLoading, isError } = useQuery({
    queryKey: ["insights", "health-summary", farmId] as const,
    queryFn: () => getFarmHealthSummary(farmId),
    enabled: Boolean(farmId),
    staleTime: 60_000,
  });

  return (
    <section
      aria-labelledby="scorecard-heading"
      className="rounded-xl border border-ap-line bg-ap-panel p-4"
    >
      <header className="flex items-baseline justify-between">
        <h2
          id="scorecard-heading"
          className="text-sm font-semibold uppercase tracking-wider text-ap-muted"
        >
          {t("scorecard.title")}
        </h2>
        <span className="text-[11px] text-ap-muted">{t("scorecard.subtitle")}</span>
      </header>

      <div className="mt-3">
        {isLoading ? (
          <Skeleton className="h-40 w-full" />
        ) : isError ? (
          <p className="py-8 text-center text-sm text-ap-crit">{t("scorecard.loadFailed")}</p>
        ) : !data || data.blocks.length === 0 ? (
          <p className="py-8 text-center text-sm text-ap-muted">{t("scorecard.empty")}</p>
        ) : (
          <table className="min-w-full divide-y divide-ap-line text-sm">
            <thead className="text-[11px] uppercase tracking-wider text-ap-muted">
              <tr>
                <th scope="col" className="px-3 py-2 text-start font-semibold">
                  {t("scorecard.headers.block")}
                </th>
                <th scope="col" className="px-3 py-2 text-start font-semibold">
                  {t("scorecard.headers.health")}
                </th>
                <th scope="col" className="px-3 py-2 text-end font-semibold">
                  {t("scorecard.headers.current")}
                </th>
                <th scope="col" className="px-3 py-2 text-end font-semibold">
                  {t("scorecard.headers.trend")}
                </th>
                <th scope="col" className="px-3 py-2 text-end font-semibold">
                  {t("scorecard.headers.alerts")}
                </th>
                <th scope="col" className="px-3 py-2 text-end font-semibold">
                  {t("scorecard.headers.lastObs")}
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ap-line">
              {data.blocks.map((b) => (
                <tr key={b.block_id} className="hover:bg-ap-bg/40">
                  <td className="px-3 py-2 text-ap-ink">
                    <Link to={`/labs/map/${farmId}?unit=${b.block_id}`} className="hover:underline">
                      {b.block_name}
                    </Link>
                  </td>
                  <td className="px-3 py-2">
                    <HealthBadge health={b.current_health} t={t} />
                  </td>
                  <td className="px-3 py-2 text-end tabular-nums text-ap-ink">
                    {b.current_value ?? "—"}
                  </td>
                  <td className="px-3 py-2 text-end tabular-nums">
                    <TrendPct value={b.trend_30d_pct} />
                  </td>
                  <td className="px-3 py-2 text-end">
                    {b.alerts_open > 0 ? (
                      <Link
                        to={`/alerts?block_id=${b.block_id}`}
                        className="rounded bg-ap-crit/10 px-1.5 py-0.5 text-[11px] font-medium text-ap-crit hover:bg-ap-crit/20"
                      >
                        {b.alerts_open}
                      </Link>
                    ) : (
                      <span className="text-[11px] text-ap-muted">0</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-end text-[11px] text-ap-muted">
                    {b.last_observation_at
                      ? formatDistanceToNow(parseISO(b.last_observation_at), {
                          addSuffix: true,
                          locale: dateLocale,
                        })
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}

const HEALTH_CHIP: Record<Health, { bg: string; fg: string }> = {
  // Same palette as the Labs map (HEALTH_FILL/HEALTH_STROKE in
  // labs/map/health.ts). Tailwind classes used here so we don't
  // import that module (no need to couple Insights to the Labs
  // surface).
  healthy: { bg: "bg-emerald-100", fg: "text-emerald-800" },
  watch: { bg: "bg-amber-100", fg: "text-amber-800" },
  critical: { bg: "bg-rose-100", fg: "text-rose-800" },
  unknown: { bg: "bg-slate-100", fg: "text-slate-700" },
};

function HealthBadge({
  health,
  t,
}: {
  health: Health;
  t: ReturnType<typeof useTranslation>["t"];
}): ReactNode {
  const { bg, fg } = HEALTH_CHIP[health];
  return (
    <span
      className={`inline-flex items-center rounded px-2 py-0.5 text-[11px] font-medium ${bg} ${fg}`}
    >
      {t(`scorecard.health.${health}`)}
    </span>
  );
}

function TrendPct({ value }: { value: string | null }): ReactNode {
  if (value === null) return <span className="text-ap-muted">—</span>;
  const num = Number(value);
  const sign = num > 0 ? "+" : "";
  const cls = num > 0 ? "text-emerald-700" : num < 0 ? "text-rose-700" : "text-ap-muted";
  return (
    <span className={cls}>
      {sign}
      {num.toFixed(1)}%
    </span>
  );
}

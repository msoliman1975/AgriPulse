import { useQuery } from "@tanstack/react-query";
import { formatDistanceToNow, parseISO } from "date-fns";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { getFarmHealthSummary, type Health } from "@/api/insights";
import { Card } from "@/components/Card";
import { Skeleton } from "@/components/Skeleton";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/Table";
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
    <Card noPadding className="p-4" aria-labelledby="scorecard-heading">
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
          <Table>
            <Thead className="text-[11px]">
              <Tr>
                <Th scope="col">{t("scorecard.headers.block")}</Th>
                <Th scope="col">{t("scorecard.headers.health")}</Th>
                <Th scope="col" className="text-end">
                  {t("scorecard.headers.current")}
                </Th>
                <Th scope="col" className="text-end">
                  {t("scorecard.headers.trend")}
                </Th>
                <Th scope="col" className="text-end">
                  {t("scorecard.headers.alerts")}
                </Th>
                <Th scope="col" className="text-end">
                  {t("scorecard.headers.lastObs")}
                </Th>
              </Tr>
            </Thead>
            <Tbody>
              {data.blocks.map((b) => (
                <Tr key={b.block_id} className="hover:bg-ap-bg/40">
                  <Td className="text-ap-ink">
                    <Link to={`/labs/map/${farmId}?unit=${b.block_id}`} className="hover:underline">
                      {b.block_name}
                    </Link>
                  </Td>
                  <Td>
                    <HealthBadge health={b.current_health} t={t} />
                  </Td>
                  <Td className="text-end tabular-nums text-ap-ink">
                    {formatIndexValue(b.current_value)}
                  </Td>
                  <Td className="text-end tabular-nums">
                    <TrendPct value={b.trend_30d_pct} />
                  </Td>
                  <Td className="text-end">
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
                  </Td>
                  <Td className="text-end text-[11px]">
                    {b.last_observation_at
                      ? formatDistanceToNow(parseISO(b.last_observation_at), {
                          addSuffix: true,
                          locale: dateLocale,
                        })
                      : "—"}
                  </Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        )}
      </div>
    </Card>
  );
}

const HEALTH_CHIP: Record<Health, { bg: string; fg: string }> = {
  // Same palette as the Labs map (HEALTH_FILL/HEALTH_STROKE in
  // labs/map/health.ts). Tailwind classes used here so we don't
  // import that module (no need to couple Insights to the Labs
  // surface).
  healthy: { bg: "bg-ap-primary-soft", fg: "text-ap-primary" },
  watch: { bg: "bg-ap-warn-soft", fg: "text-ap-warn" },
  critical: { bg: "bg-ap-crit-soft", fg: "text-ap-crit" },
  unknown: { bg: "bg-ap-bg", fg: "text-ap-ink" },
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

/**
 * The API returns the index value as a raw numeric string (e.g.
 * "0.2060000000000000000"). Show it at the same 2-decimal precision the
 * Farm Console units rail uses so the two surfaces agree.
 */
function formatIndexValue(value: string | null): string {
  if (value === null) return "—";
  const num = Number(value);
  return Number.isFinite(num) ? num.toFixed(2) : value;
}

function TrendPct({ value }: { value: string | null }): ReactNode {
  if (value === null) return <span className="text-ap-muted">—</span>;
  const num = Number(value);
  const sign = num > 0 ? "+" : "";
  const cls = num > 0 ? "text-ap-primary" : num < 0 ? "text-ap-crit" : "text-ap-muted";
  return (
    <span className={cls}>
      {sign}
      {num.toFixed(1)}%
    </span>
  );
}

import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Line, LineChart, ResponsiveContainer, Tooltip } from "recharts";

import { getFarmAlertTrend } from "@/api/insights";

interface Props {
  farmId: string;
  days?: number; // default 7
}

/**
 * Tiny sparkline under the "Active alerts" KPI. Renders the daily
 * open-alert count for the last N days — no axes, no legend, just a
 * shape so the operator can see trajectory at a glance.
 *
 * Colour follows the latest point's value: red when current count >
 * 0 (rising or steady at non-zero), grey when zero (all clear). The
 * tooltip carries the exact count + date on hover for the rare case
 * the operator wants the number behind the shape.
 *
 * Other KPIs (land units, recommendations, irrigation due, upcoming
 * activities) don't have queryable history yet; they get sparklines
 * once the underlying tables grow a `recorded_at` snapshot or we
 * add a daily-rollup CAGG.
 */
export function AlertsSparkline({ farmId, days = 7 }: Props): ReactNode {
  const { data, isLoading } = useQuery({
    queryKey: ["insights", "alert-trend", farmId, days] as const,
    queryFn: () => getFarmAlertTrend(farmId, days),
    enabled: Boolean(farmId),
    staleTime: 60_000,
  });

  if (isLoading) {
    return <div className="mt-1 h-6 w-full animate-pulse rounded bg-ap-line/40" />;
  }
  if (!data || data.points.length === 0) return null;

  const latest = data.points[data.points.length - 1];
  const stroke = latest.open_count > 0 ? "#A32D2D" : "#9C9C9C";

  return (
    <div className="mt-1 h-6 w-full" aria-hidden>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data.points} margin={{ top: 1, right: 1, bottom: 1, left: 1 }}>
          <Tooltip
            contentStyle={{ padding: "2px 6px", fontSize: 10 }}
            labelFormatter={(label: string) => new Date(label).toLocaleDateString()}
            formatter={(value: number) => [value, "open"]}
          />
          <Line
            type="monotone"
            dataKey="open_count"
            stroke={stroke}
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

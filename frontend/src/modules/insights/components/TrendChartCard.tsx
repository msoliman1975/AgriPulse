import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { listBlocks } from "@/api/blocks";
import { Skeleton } from "@/components/Skeleton";
import { IndexTrendChart } from "@/modules/indices/components/IndexTrendChart";

interface Props {
  farmId: string;
}

/**
 * Pulls the farm's first block and renders its NDVI trend.
 * A real farm-rollup endpoint is parked in IMPLEMENTATION_PLAN §5.5; once
 * `GET /farms/{id}/index-timeseries` exists we'll switch to that.
 */
export function TrendChartCard({ farmId }: Props): ReactNode {
  const { data, isLoading } = useQuery({
    queryKey: ["blocks", "list", farmId] as const,
    queryFn: () => listBlocks(farmId),
    enabled: Boolean(farmId),
  });
  const firstBlock = data?.items[0];

  return (
    <section
      aria-labelledby="trend-heading"
      className="rounded-xl border border-ap-line bg-ap-panel p-4"
    >
      <header className="flex items-baseline justify-between">
        <h2
          id="trend-heading"
          className="text-sm font-semibold uppercase tracking-wider text-ap-muted"
        >
          Vegetation index trend
        </h2>
        {firstBlock ? (
          <span className="text-[11px] text-ap-muted">{firstBlock.name ?? firstBlock.code}</span>
        ) : null}
      </header>
      <div className="mt-3 min-h-[220px]">
        {isLoading ? (
          <Skeleton className="h-56 w-full" />
        ) : !firstBlock ? (
          <p className="py-12 text-center text-sm text-ap-muted">No blocks to chart yet.</p>
        ) : (
          <IndexTrendChart blockId={firstBlock.id} />
        )}
      </div>
    </section>
  );
}

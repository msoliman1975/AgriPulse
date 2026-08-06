import { useQuery } from "@tanstack/react-query";
import type { UseQueryResult } from "@tanstack/react-query";

import {
  getObserverHistogram,
  getObserverOverview,
  getSceneIndices,
  listObserverFarms,
  listObserverProducts,
  listObserverScenes,
  listObserverTenants,
  explainPixel,
  getPixelBudget,
  getSceneDetail,
  type HistogramBucket,
  type HistogramBucketSize,
  type ObserverFarm,
  type ObserverIndexRow,
  type ObserverOverview,
  type ObserverProduct,
  type ObserverScene,
  type ObserverScope,
  type ObserverTenant,
  type PixelBudget,
  type PixelExplain,
  type SceneDetail,
  type SceneFilters,
} from "@/api/observer";

const ROOT = "observer";

// Observer reports history, not live state: nothing it shows changes on a
// second-by-second basis, and the overview costs several hypertable
// aggregates per call. So every query here is deliberately stale-tolerant
// and none of them poll.
const STALE = 60_000;

/** Serializes a scope into a stable query key. */
function scopeKey(scope: ObserverScope): unknown[] {
  return [
    scope.farmId,
    scope.from,
    scope.to,
    [...(scope.blockIds ?? [])].sort().join(","),
    scope.productId ?? "",
  ];
}

export function useObserverTenants(): UseQueryResult<ObserverTenant[]> {
  return useQuery({
    queryKey: [ROOT, "tenants"],
    queryFn: listObserverTenants,
    staleTime: STALE,
  });
}

export function useObserverFarms(tenantId: string | null): UseQueryResult<ObserverFarm[]> {
  return useQuery({
    queryKey: [ROOT, "farms", tenantId],
    queryFn: () => listObserverFarms(tenantId as string),
    enabled: Boolean(tenantId),
    staleTime: STALE,
  });
}

export function useObserverProducts(
  tenantId: string | null,
  farmId: string | null,
): UseQueryResult<ObserverProduct[]> {
  return useQuery({
    queryKey: [ROOT, "products", tenantId, farmId],
    queryFn: () => listObserverProducts(tenantId as string, farmId as string),
    enabled: Boolean(tenantId && farmId),
    staleTime: STALE,
  });
}

export function useObserverOverview(
  tenantId: string | null,
  scope: ObserverScope | null,
): UseQueryResult<ObserverOverview> {
  return useQuery({
    queryKey: [ROOT, "overview", tenantId, ...(scope ? scopeKey(scope) : [])],
    queryFn: () => getObserverOverview(tenantId as string, scope as ObserverScope),
    enabled: Boolean(tenantId && scope),
    staleTime: STALE,
  });
}

export function useObserverHistogram(
  tenantId: string | null,
  scope: ObserverScope | null,
  bucket: HistogramBucketSize,
): UseQueryResult<HistogramBucket[]> {
  return useQuery({
    queryKey: [ROOT, "histogram", tenantId, bucket, ...(scope ? scopeKey(scope) : [])],
    queryFn: () => getObserverHistogram(tenantId as string, scope as ObserverScope, bucket),
    enabled: Boolean(tenantId && scope),
    staleTime: STALE,
  });
}

export function useObserverScenes(
  tenantId: string | null,
  scope: ObserverScope | null,
  filters: SceneFilters,
): UseQueryResult<ObserverScene[]> {
  return useQuery({
    queryKey: [
      ROOT,
      "scenes",
      tenantId,
      ...(scope ? scopeKey(scope) : []),
      [...(filters.status ?? [])].sort().join(","),
      filters.maxValidPct ?? "",
      filters.withError ?? false,
      filters.offset ?? 0,
    ],
    queryFn: () => listObserverScenes(tenantId as string, scope as ObserverScope, filters),
    enabled: Boolean(tenantId && scope),
    staleTime: STALE,
  });
}

export function useSceneIndices(
  tenantId: string | null,
  args: { blockId: string; productId: string; sceneTime: string } | null,
): UseQueryResult<ObserverIndexRow[]> {
  return useQuery({
    queryKey: [ROOT, "sceneIndices", tenantId, args?.blockId, args?.productId, args?.sceneTime],
    queryFn: () => getSceneIndices(tenantId as string, args as NonNullable<typeof args>),
    enabled: Boolean(tenantId && args),
    staleTime: STALE,
  });
}

// ---- L2 ------------------------------------------------------------------

export function useSceneDetail(
  tenantId: string | null,
  jobId: string | null,
): UseQueryResult<SceneDetail> {
  return useQuery({
    queryKey: [ROOT, "sceneDetail", tenantId, jobId],
    queryFn: () => getSceneDetail(tenantId as string, jobId as string),
    enabled: Boolean(tenantId && jobId),
    staleTime: STALE,
  });
}

/**
 * The pixel budget is recomputed from the COG on every call, so it is
 * deliberately not fetched until the operator asks for it — opening a scene
 * should not read a raster.
 */
export function usePixelBudget(
  tenantId: string | null,
  jobId: string | null,
  enabled: boolean,
): UseQueryResult<PixelBudget> {
  return useQuery({
    queryKey: [ROOT, "pixelBudget", tenantId, jobId],
    queryFn: () => getPixelBudget(tenantId as string, jobId as string),
    enabled: Boolean(tenantId && jobId && enabled),
    staleTime: Infinity,
  });
}

/** One GDAL range read per click; cached forever since a pixel never changes. */
export function usePixelExplain(
  tenantId: string | null,
  jobId: string | null,
  point: { lon: number; lat: number } | null,
): UseQueryResult<PixelExplain> {
  return useQuery({
    queryKey: [ROOT, "pixel", tenantId, jobId, point?.lon, point?.lat],
    queryFn: () =>
      explainPixel(
        tenantId as string,
        jobId as string,
        (point as { lon: number; lat: number }).lon,
        (point as { lon: number; lat: number }).lat,
      ),
    enabled: Boolean(tenantId && jobId && point),
    staleTime: Infinity,
    retry: false,
  });
}

import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";

import type { HistogramBucketSize, JobStatus, ObserverScope } from "@/api/observer";
import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { Pill } from "@/components/Pill";
import { SegmentedControl } from "@/components/SegmentedControl";
import { Skeleton } from "@/components/Skeleton";
import { SceneHistogram } from "@/modules/admin/components/observer/SceneHistogram";
import { SceneTable } from "@/modules/admin/components/observer/SceneTable";
import { StageRibbon } from "@/modules/admin/components/observer/StageRibbon";
import { VerifyRunsCard } from "@/modules/admin/components/observer/VerifyRunsCard";
import { WeatherLane } from "@/modules/admin/components/observer/WeatherLane";
import {
  useObserverFarms,
  useObserverHistogram,
  useObserverOverview,
  useObserverProducts,
  useObserverScenes,
  useObserverTenants,
} from "@/queries/observer";

/**
 * AgriPulse Observer — /platform/observer.
 *
 * Every part of the selection lives in the query string rather than in
 * component state. An operator who finds something wrong needs to hand the
 * exact view to someone else, and "select these six things in this order"
 * is not a handover.
 */

const DEFAULT_WINDOW_DAYS = 90;

function isoDaysAgo(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

/** Day strings from the date inputs → the instants the API expects. */
function dayToInstant(day: string, endOfDay: boolean): string {
  return new Date(`${day}T${endOfDay ? "23:59:59" : "00:00:00"}Z`).toISOString();
}

export function PlatformObserverPage(): ReactNode {
  const { t } = useTranslation("admin");
  const [params, setParams] = useSearchParams();

  const tenantId = params.get("tenant");
  const farmId = params.get("farm");
  const productId = params.get("product");
  const blockIds = params.getAll("blocks");
  const from = params.get("from") ?? isoDaysAgo(DEFAULT_WINDOW_DAYS);
  const to = params.get("to") ?? todayIso();
  const bucket = (params.get("bucket") as HistogramBucketSize | null) ?? "week";
  const source = params.get("src") === "weather" ? "weather" : "imagery";

  const [selectedStage, setSelectedStage] = useState<string | null>(null);
  const [expandedScene, setExpandedScene] = useState<string | null>(null);

  const patch = (next: Record<string, string | string[] | null>): void => {
    const merged = new URLSearchParams(params);
    for (const [key, value] of Object.entries(next)) {
      merged.delete(key);
      if (Array.isArray(value)) {
        value.forEach((v) => merged.append(key, v));
      } else if (value !== null && value !== "") {
        merged.set(key, value);
      }
    }
    setParams(merged, { replace: true });
  };

  const tenants = useObserverTenants();
  const farms = useObserverFarms(tenantId);
  const products = useObserverProducts(tenantId, farmId);

  const scope: ObserverScope | null = useMemo(
    () =>
      farmId
        ? {
            farmId,
            from: dayToInstant(from, false),
            to: dayToInstant(to, true),
            blockIds,
            productId,
          }
        : null,
    // `blockIds` is a fresh array each render; join it so the memo is stable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [farmId, from, to, blockIds.join(","), productId],
  );

  const overview = useObserverOverview(tenantId, scope);
  const histogram = useObserverHistogram(tenantId, scope, bucket);

  // Clicking a ribbon stage filters the scene list to the rows that stage is
  // actually about — which is the difference between "31 failed somewhere"
  // and a list of the 31.
  const sceneFilters = useMemo(() => {
    const statusesFor: Record<string, JobStatus[] | undefined> = {
      acquired: ["failed"],
      discovered: undefined,
    };
    return {
      status: selectedStage ? statusesFor[selectedStage] : undefined,
      limit: 200,
    };
  }, [selectedStage]);

  const scenes = useObserverScenes(tenantId, scope, sceneFilters);

  const selectedFarm = farms.data?.find((f) => f.id === farmId);

  return (
    <Page>
      <PageHeader
        title={t("observer.title")}
        badge={<Pill kind="info">{t("observer.readOnly")}</Pill>}
        subtitle={t("observer.subtitle")}
      />

      <Card title={t("observer.rail.title")}>
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <span className="mb-1 block text-xs font-medium text-ap-muted">
              {t("observer.rail.source")}
            </span>
            <SegmentedControl
              ariaLabel={t("observer.rail.source")}
              value={source}
              onChange={(v) => patch({ src: v })}
              items={[
                { value: "imagery", label: t("observer.rail.imagery") },
                { value: "weather", label: t("observer.rail.weather") },
              ]}
            />
          </div>
          <label className="min-w-[10rem] flex-1">
            <span className="mb-1 block text-xs font-medium text-ap-muted">
              {t("observer.rail.tenant")}
            </span>
            <select
              className="w-full rounded border border-ap-line bg-ap-panel px-2 py-1.5 text-sm"
              value={tenantId ?? ""}
              onChange={(e) =>
                patch({ tenant: e.target.value, farm: null, blocks: null, product: null })
              }
            >
              <option value="">{t("observer.rail.pick")}</option>
              {(tenants.data ?? []).map((tn) => (
                <option key={tn.id} value={tn.id}>
                  {tn.name}
                </option>
              ))}
            </select>
          </label>

          <label className="min-w-[12rem] flex-1">
            <span className="mb-1 block text-xs font-medium text-ap-muted">
              {t("observer.rail.farm")}
            </span>
            <select
              className="w-full rounded border border-ap-line bg-ap-panel px-2 py-1.5 text-sm"
              value={farmId ?? ""}
              disabled={!tenantId}
              onChange={(e) => patch({ farm: e.target.value, blocks: null, product: null })}
            >
              <option value="">{t("observer.rail.pick")}</option>
              {(farms.data ?? []).map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name ?? f.code} ({f.block_count})
                </option>
              ))}
            </select>
          </label>

          {source === "imagery" ? (
            <label className="min-w-[9rem] flex-1">
              <span className="mb-1 block text-xs font-medium text-ap-muted">
                {t("observer.rail.product")}
              </span>
              <select
                className="w-full rounded border border-ap-line bg-ap-panel px-2 py-1.5 text-sm"
                value={productId ?? ""}
                disabled={!farmId}
                onChange={(e) => patch({ product: e.target.value })}
              >
                <option value="">{t("observer.rail.allProducts")}</option>
                {(products.data ?? []).map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} ({p.resolution_m} m)
                  </option>
                ))}
              </select>
            </label>
          ) : null}

          <label className="min-w-[8rem]">
            <span className="mb-1 block text-xs font-medium text-ap-muted">
              {t("observer.rail.from")}
            </span>
            <input
              type="date"
              className="w-full rounded border border-ap-line bg-ap-panel px-2 py-1.5 text-sm"
              value={from}
              onChange={(e) => patch({ from: e.target.value })}
            />
          </label>

          <label className="min-w-[8rem]">
            <span className="mb-1 block text-xs font-medium text-ap-muted">
              {t("observer.rail.to")}
            </span>
            <input
              type="date"
              className="w-full rounded border border-ap-line bg-ap-panel px-2 py-1.5 text-sm"
              value={to}
              onChange={(e) => patch({ to: e.target.value })}
            />
          </label>
        </div>

        {/*
         * The farm summary is the answer to "is there anything to observe
         * here". A farm that was never subscribed and a farm whose pipeline
         * is broken both report zero scenes; only these numbers tell them
         * apart, so they sit next to the picker rather than being buried.
         */}
        {selectedFarm ? (
          <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 border-t border-ap-line pt-3 text-xs text-ap-muted">
            <span>
              {t("observer.rail.blocks")}: <strong>{selectedFarm.block_count}</strong>
            </span>
            <span>
              {t("observer.rail.withImagery")}:{" "}
              <strong>{selectedFarm.blocks_with_imagery_sub}</strong>
            </span>
            <span>
              {t("observer.rail.gridded")}: <strong>{selectedFarm.blocks_with_grid}</strong>
            </span>
            <span>
              {t("observer.rail.weather")}:{" "}
              <strong>{selectedFarm.has_weather_sub ? t("observer.yes") : t("observer.no")}</strong>
            </span>
            {selectedFarm.first_scene_at ? (
              <span>
                {t("observer.rail.sceneRange")}:{" "}
                <strong>
                  {selectedFarm.first_scene_at.slice(0, 10)} →{" "}
                  {selectedFarm.last_scene_at?.slice(0, 10)}
                </strong>
              </span>
            ) : (
              <span className="text-ap-warn">{t("observer.rail.noScenes")}</span>
            )}
          </div>
        ) : null}
      </Card>

      {!farmId ? (
        <EmptyState message={t("observer.pickFarmFirst")} />
      ) : source === "weather" ? (
        <WeatherLane
          tenantId={tenantId as string}
          farmId={farmId}
          windowFrom={dayToInstant(from, false)}
          windowTo={dayToInstant(to, true)}
        />
      ) : (
        <>
          {overview.isPending ? (
            <Skeleton className="h-40 w-full" />
          ) : overview.data ? (
            <StageRibbon
              overview={overview.data}
              selectedStage={selectedStage}
              onSelectStage={setSelectedStage}
            />
          ) : null}

          <SceneHistogram
            buckets={histogram.data ?? []}
            bucket={bucket}
            onBucketChange={(b) => patch({ bucket: b })}
            isLoading={histogram.isPending}
          />

          <VerifyRunsCard
            tenantId={tenantId as string}
            farmId={farmId}
            windowFrom={dayToInstant(from, false)}
            windowTo={dayToInstant(to, true)}
            blockIds={blockIds}
            productId={productId}
          />

          <Card
            title={t("observer.scenes.title")}
            actions={
              selectedStage ? (
                <button
                  type="button"
                  className="text-xs text-ap-accent underline"
                  onClick={() => setSelectedStage(null)}
                >
                  {t("observer.scenes.clearFilter")}
                </button>
              ) : null
            }
            noPadding
          >
            <SceneTable
              tenantId={tenantId as string}
              farmId={farmId}
              scenes={scenes.data ?? []}
              isLoading={scenes.isPending}
              isError={scenes.isError}
              expanded={expandedScene}
              onToggleExpand={setExpandedScene}
            />
          </Card>
        </>
      )}
    </Page>
  );
}

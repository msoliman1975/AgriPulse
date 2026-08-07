import { lazy, Suspense, useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useParams, useSearchParams } from "react-router-dom";
import type { Geometry } from "geojson";

import { Breadcrumb } from "@/components/Breadcrumb";
import { Card } from "@/components/Card";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { Pill } from "@/components/Pill";
import { Skeleton } from "@/components/Skeleton";
import {
  buildTileUrlTemplate,
  indexAssetKey,
  visualizationDefaults,
} from "@/modules/imagery/components/tileUrl";
import type { IndexCode } from "@/api/indices";
import { PixelBudgetCard } from "@/modules/admin/components/observer/PixelBudgetCard";
import { PixelInspector } from "@/modules/admin/components/observer/PixelInspector";
import {
  usePixelBudget,
  usePixelExplain,
  useSceneDetail,
  useSceneIndices,
} from "@/queries/observer";

// MapLibre needs WebGL, which jsdom does not provide, so the map is loaded
// lazily — the rest of this page stays unit-testable.
const ObserverSceneMap = lazy(() =>
  import("@/modules/admin/components/observer/ObserverSceneMap").then((m) => ({
    default: m.ObserverSceneMap,
  })),
);

/**
 * One scene, explained: what went in, what the maths did, what came out, and
 * how a single pixel rolls up into the cell and block numbers.
 */
export function ObserverSceneDetailPage(): ReactNode {
  const { t, i18n } = useTranslation("admin");
  const { jobId } = useParams<{ jobId: string }>();
  const [params, setParams] = useSearchParams();

  const tenantId = params.get("tenant");
  const selectedIndex = params.get("index") ?? "ndvi";

  const [picked, setPicked] = useState<{ lon: number; lat: number } | null>(null);
  const [budgetRequested, setBudgetRequested] = useState(false);

  const detail = useSceneDetail(tenantId, jobId ?? null);
  const pixel = usePixelExplain(tenantId, jobId ?? null, picked);
  const budget = usePixelBudget(tenantId, jobId ?? null, budgetRequested);
  const indices = useSceneIndices(
    tenantId,
    detail.data
      ? {
          blockId: detail.data.block_id,
          productId: detail.data.product_id,
          sceneTime: detail.data.scene_datetime,
        }
      : null,
  );

  const tileUrl = useMemo(() => {
    const d = detail.data;
    if (!d || !d.raw_asset_key) return null;
    if (!d.supported_indices.includes(selectedIndex)) return null;
    const vis = visualizationDefaults(selectedIndex as IndexCode);
    return buildTileUrlTemplate({
      tileServerBaseUrl: d.tile_server_base_url,
      s3Bucket: d.s3_bucket,
      assetKey: indexAssetKey({
        providerCode: d.provider_code,
        productCode: d.product_code,
        sceneId: d.scene_id,
        aoiHash: d.aoi_hash,
        indexCode: selectedIndex as IndexCode,
      }),
      rescaleMin: vis.rescaleMin,
      rescaleMax: vis.rescaleMax,
      colormap: vis.colormap,
    });
  }, [detail.data, selectedIndex]);

  if (detail.isPending) return <Skeleton className="h-96 w-full" />;
  if (!detail.data) return <Page>{t("observer.detail.notFound")}</Page>;

  const d = detail.data;
  const blockLabel = d.block_name ?? d.block_code ?? d.block_id;
  const aggregateRow = indices.data?.find((r) => r.index_code === selectedIndex);

  return (
    <Page>
      <Breadcrumb
        items={[
          {
            label: t("observer.title"),
            to: `/platform/observer?tenant=${tenantId ?? ""}&farm=${d.farm_id}`,
          },
          { label: `${blockLabel} · ${d.scene_id}` },
        ]}
      />
      <PageHeader
        title={`${blockLabel} — ${new Date(d.scene_datetime).toLocaleString(i18n.language)}`}
        badge={<Pill kind={d.status === "succeeded" ? "ok" : "crit"}>{d.status}</Pill>}
        subtitle={`${d.provider_name} · ${d.product_name} · ${d.resolution_m} m`}
        actions={
          <select
            className="rounded border border-ap-line bg-ap-panel px-2 py-1.5 text-sm"
            value={selectedIndex}
            onChange={(e) => {
              const merged = new URLSearchParams(params);
              merged.set("index", e.target.value);
              setParams(merged, { replace: true });
            }}
            aria-label={t("observer.detail.index")}
          >
            {d.supported_indices.map((code) => (
              <option key={code} value={code}>
                {code.toUpperCase()}
              </option>
            ))}
          </select>
        }
      />

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_24rem]">
        <Card title={t("observer.detail.raster")} noPadding>
          {d.raw_asset_key ? (
            <Suspense fallback={<Skeleton className="h-96 w-full" />}>
              <ObserverSceneMap
                geometry={d.boundary_geojson as unknown as Geometry}
                tileUrlTemplate={tileUrl}
                picked={picked}
                onPick={setPicked}
                className="h-96 w-full rounded-b-card"
              />
            </Suspense>
          ) : (
            <p className="p-4 text-sm text-ap-muted">{t("observer.detail.noRaster")}</p>
          )}
        </Card>

        <PixelInspector
          data={pixel.data}
          isPending={pixel.isFetching}
          error={pixel.error}
          selectedIndex={selectedIndex}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <PixelBudgetCard
          budget={budget.data}
          isPending={budget.isPending}
          requested={budgetRequested}
          onRequest={() => setBudgetRequested(true)}
          selectedIndex={selectedIndex}
        />

        <Card title={t("observer.detail.inputs")}>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
            <dt className="text-ap-muted">{t("observer.detail.rawAsset")}</dt>
            <dd className="break-all font-mono">{d.raw_asset_key ?? "—"}</dd>
            <dt className="text-ap-muted">{t("observer.detail.bands")}</dt>
            <dd>{d.bands.join(", ")}</dd>
            <dt className="text-ap-muted">{t("observer.detail.aoiHash")}</dt>
            <dd className="font-mono">{d.aoi_hash}</dd>
            <dt className="text-ap-muted">{t("observer.detail.maskRuleset")}</dt>
            <dd className="font-mono">
              {d.mask_ruleset} ({d.mask_classes.join(", ")})
            </dd>
            <dt className="text-ap-muted">{t("observer.detail.grid")}</dt>
            <dd>
              {d.grid ? (
                <>
                  {d.grid.cell_size_m} m · {d.grid.cell_count} {t("observer.detail.cells")} · UTM{" "}
                  {d.grid.utm_srid}
                  {/*
                   * Valid time, not "the current grid": a 2025 scene was
                   * gridded on the geometry that governed 2025, and showing
                   * today's would attribute cells it never had.
                   */}
                  <span className="ms-1 text-ap-muted">
                    {t("observer.detail.gridValidFrom", {
                      from: d.grid.effective_from?.slice(0, 10) ?? "—",
                    })}
                  </span>
                </>
              ) : (
                <span className="text-ap-muted">{t("observer.detail.noGrid")}</span>
              )}
            </dd>
            <dt className="text-ap-muted">{t("observer.detail.stacItem")}</dt>
            <dd className="break-all font-mono">{d.stac_item_id ?? "—"}</dd>
            {d.error_message ? (
              <>
                <dt className="text-ap-muted">{t("observer.detail.error")}</dt>
                <dd className="text-ap-crit">{d.error_message}</dd>
              </>
            ) : null}
          </dl>
        </Card>
      </div>

      <Card title={t("observer.detail.rollup")}>
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <RollupChip
            label={t("observer.detail.pixel")}
            value={
              pixel.data?.indices[selectedIndex]?.raw_value?.toFixed(4) ??
              t("observer.detail.clickPixel")
            }
          />
          <span className="text-ap-muted">→</span>
          <RollupChip
            label={t("observer.detail.cell")}
            value={d.grid ? t("observer.detail.cellCount", { n: d.grid.cell_count }) : "—"}
          />
          <span className="text-ap-muted">→</span>
          <RollupChip
            label={t("observer.detail.blockMean")}
            value={aggregateRow?.mean?.toString() ?? "—"}
            sub={
              aggregateRow
                ? t("observer.detail.validOf", {
                    valid: aggregateRow.valid_pixel_count.toLocaleString(),
                    total: aggregateRow.total_pixel_count.toLocaleString(),
                  })
                : undefined
            }
          />
        </div>
        <p className="mt-3 border-s-2 border-ap-accent ps-3 text-xs text-ap-muted">
          {t("observer.detail.rollupNote")}
        </p>
      </Card>
    </Page>
  );
}

function RollupChip({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}): ReactNode {
  return (
    <div className="min-w-[8rem] rounded border border-ap-line bg-ap-bg/40 px-3 py-2">
      <div className="text-[0.625rem] font-semibold uppercase tracking-wide text-ap-muted">
        {label}
      </div>
      <div className="text-base font-semibold tabular-nums">{value}</div>
      {sub ? <div className="text-[0.625rem] text-ap-muted">{sub}</div> : null}
    </div>
  );
}

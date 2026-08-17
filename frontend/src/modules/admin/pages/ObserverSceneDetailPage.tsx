import { lazy, Suspense, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useParams, useSearchParams } from "react-router-dom";
import type { Geometry } from "geojson";

import { Breadcrumb } from "@/components/Breadcrumb";
import { Card } from "@/components/Card";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { Pill } from "@/components/Pill";
import { Skeleton } from "@/components/Skeleton";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/Table";
import { visualizationDefaults } from "@/modules/imagery/components/tileUrl";
import type { IndexCode } from "@/api/indices";
import { PixelBudgetCard } from "@/modules/admin/components/observer/PixelBudgetCard";
import { CellDrillPanel } from "@/modules/admin/components/observer/CellDrillPanel";
import { LineagePanel } from "@/modules/admin/components/observer/LineagePanel";
import { PixelInspector } from "@/modules/admin/components/observer/PixelInspector";
import { VerifyPanel } from "@/modules/admin/components/observer/VerifyPanel";
import {
  usePixelBudget,
  usePixelGrid,
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
/** Value window for the pixel ramp — imagery's own per-index defaults. */
function rescaleFor(indexCode: string): [number, number] {
  const vis = visualizationDefaults(indexCode as IndexCode);
  return [vis.rescaleMin, vis.rescaleMax];
}

export function ObserverSceneDetailPage(): ReactNode {
  const { t, i18n } = useTranslation("admin");
  const { jobId } = useParams<{ jobId: string }>();
  const [params, setParams] = useSearchParams();

  const tenantId = params.get("tenant");
  const requestedIndex = params.get("index");

  const [picked, setPicked] = useState<{ lon: number; lat: number } | null>(null);
  const [budgetRequested, setBudgetRequested] = useState(false);
  const [selectedCell, setSelectedCell] = useState<string | null>(null);

  const detail = useSceneDetail(tenantId, jobId ?? null);
  // The index set belongs to the PRODUCT. Defaulting to "ndvi" asked a
  // Landsat thermal scene — which offers only lst/cwsi/smi — for a raster
  // that cannot exist, so the map came back blank and the request 422'd.
  // Null until the product is known, which is what keeps the grid query
  // from firing on a guess.
  const supported = detail.data?.supported_indices;
  const selectedIndex =
    supported === undefined
      ? null
      : requestedIndex && supported.includes(requestedIndex)
        ? requestedIndex
        : (supported[0] ?? null);

  const pixel = usePixelExplain(tenantId, jobId ?? null, picked);
  const budget = usePixelBudget(tenantId, jobId ?? null, budgetRequested);
  const grid = usePixelGrid(tenantId, jobId ?? null, selectedIndex, selectedCell);
  const indices = useSceneIndices(
    tenantId,
    detail.data
      ? {
          // A whole-farm scene carries no block; its aggregates are asked
          // for by farm and come back one row per (block, index).
          blockId: detail.data.block_id,
          farmId: detail.data.farm_id,
          productId: detail.data.product_id,
          sceneTime: detail.data.scene_datetime,
        }
      : null,
  );

  if (detail.isPending) return <Skeleton className="h-96 w-full" />;
  if (!detail.data) return <Page>{t("observer.detail.notFound")}</Page>;

  const d = detail.data;
  const blockLabel = d.block_name ?? d.block_code ?? d.block_id;
  // Narrowed: `supported_indices` is resolved now that `detail.data` is, so
  // the index is a concrete one belonging to THIS scene's product.
  const indexCode = selectedIndex ?? d.supported_indices[0] ?? "ndvi";
  const aggregateRow = indices.data?.find((r) => r.index_code === indexCode);

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
            value={indexCode}
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
        <Card
          title={t("observer.detail.raster")}
          actions={
            grid.data ? (
              <span className="text-xs text-ap-muted">
                {grid.data.returned_pixel_count} px · {grid.data.cells.length} cells
              </span>
            ) : null
          }
          noPadding
        >
          {d.raw_asset_key ? (
            <Suspense fallback={<Skeleton className="h-[28rem] w-full" />}>
              {grid.data ? (
                <>
                  <ObserverSceneMap
                    boundary={d.boundary_geojson as unknown as Geometry}
                    pixels={grid.data.pixels}
                    cells={grid.data.cells}
                    selectedCellId={selectedCell}
                    onSelectCell={setSelectedCell}
                    onPickPixel={setPicked}
                    rescale={rescaleFor(indexCode)}
                    className="h-[28rem] w-full"
                  />
                  <p className="border-t border-ap-line p-3 text-xs text-ap-muted">
                    {t("observer.cells.legend")}
                  </p>
                </>
              ) : (
                <Skeleton className="h-[28rem] w-full" />
              )}
            </Suspense>
          ) : (
            <p className="p-4 text-sm text-ap-muted">{t("observer.detail.noRaster")}</p>
          )}
        </Card>

        <div className="space-y-4">
          <CellDrillPanel
            grid={grid.data}
            selectedCellId={selectedCell}
            onClear={() => setSelectedCell(null)}
            isFetching={grid.isFetching}
          />
          <PixelInspector
            data={pixel.data}
            isPending={pixel.isFetching}
            error={pixel.error}
            selectedIndex={indexCode}
          />
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <PixelBudgetCard
          budget={budget.data}
          isPending={budget.isPending}
          requested={budgetRequested}
          onRequest={() => setBudgetRequested(true)}
          selectedIndex={indexCode}
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
              {/* Classes for Sentinel-2's SCL enum, bit positions for
                  Landsat's QA_PIXEL bitmask. Exactly one is populated, and
                  printing an empty "()" on thermal read as "masks nothing". */}
              {d.mask_ruleset}
              {d.mask_classes.length > 0
                ? ` (${t("observer.detail.maskClasses")}: ${d.mask_classes.join(", ")})`
                : d.mask_bits.length > 0
                  ? ` (${t("observer.detail.maskBits")}: ${d.mask_bits.join(", ")})`
                  : ""}
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

      {/*
        Verification and lineage are both keyed on one block: they diff
        against, and trace forward from, that block's stored rows. A
        whole-farm acquisition wrote a row on EVERY block of the farm, so
        there is no single block to name — and silently picking one would
        report a verdict about a scene the operator did not ask about.
        Say so and point at the block scenes instead.
      */}
      {d.block_id === null ? (
        <Card title={t("observer.detail.wholeFarmTitle")}>
          <p className="text-sm text-ap-muted">{t("observer.detail.wholeFarmNote")}</p>
        </Card>
      ) : (
        <>
          <VerifyPanel tenantId={tenantId as string} jobId={jobId as string} />

          <LineagePanel
            tenantId={tenantId as string}
            blockId={d.block_id}
            indexCode={indexCode}
            productId={d.product_id}
            sceneTime={d.scene_datetime}
            // A scene's consumers are what fired in the days after it, so the
            // window opens at the scene and runs a fortnight forward rather
            // than spanning the operator's whole selection.
            windowFrom={d.scene_datetime}
            windowTo={new Date(
              new Date(d.scene_datetime).getTime() + 14 * 24 * 3600 * 1000,
            ).toISOString()}
          />
        </>
      )}

      <Card
        title={t("observer.detail.history")}
        actions={
          /*
           * More than one calc version on one scene means the aggregate row
           * was replaced by a different build. The row itself is an upsert
           * and cannot show that; only these run records can.
           */
          new Set(d.calc_runs.map((r) => r.calc_version)).size > 1 ? (
            <Pill kind="warn">{t("observer.detail.overwritten")}</Pill>
          ) : null
        }
        noPadding
      >
        {d.calc_runs.length === 0 ? (
          <p className="p-4 text-xs text-ap-muted">{t("observer.detail.noHistory")}</p>
        ) : (
          <Table className="text-xs">
            <Thead>
              <Tr>
                <Th>{t("observer.detail.when")}</Th>
                <Th>{t("observer.detail.trigger")}</Th>
                <Th>{t("observer.detail.calcVersion")}</Th>
                <Th className="text-end">{t("observer.detail.maskedPx")}</Th>
                <Th className="text-end">{t("observer.detail.durationMs")}</Th>
                <Th>{t("observer.detail.outcome")}</Th>
              </Tr>
            </Thead>
            <Tbody>
              {d.calc_runs.map((run) => (
                <Tr key={run.id}>
                  <Td className="tabular-nums">
                    {new Date(run.created_at).toLocaleString(i18n.language)}
                  </Td>
                  <Td>{run.trigger}</Td>
                  <Td className="font-mono">{run.calc_version}</Td>
                  <Td className="text-end tabular-nums">
                    {run.masked_pixel_count?.toLocaleString() ?? "—"}
                  </Td>
                  <Td className="text-end tabular-nums">
                    {run.duration_ms?.toLocaleString() ?? "—"}
                  </Td>
                  <Td>
                    <Pill kind={run.outcome === "ok" ? "ok" : "crit"}>{run.outcome}</Pill>
                    {run.error ? (
                      <span className="ms-2 text-ap-muted" title={run.error}>
                        {run.error.slice(0, 60)}
                      </span>
                    ) : null}
                  </Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        )}
      </Card>

      <Card title={t("observer.detail.rollup")}>
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <RollupChip
            label={t("observer.detail.pixel")}
            value={
              pixel.data?.indices[indexCode]?.raw_value?.toFixed(4) ??
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

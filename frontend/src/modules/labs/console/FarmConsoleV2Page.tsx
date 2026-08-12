// Farm Console v2 — the unified console (/labs/map-v2).
//
// Runs BESIDE /labs/map, which stays the default, until this clears the
// cutover bar: every capability of the live console present, browser-verified
// in EN and AR/RTL, tested on real farm data, and covered by automated tests.
// See docs/proposals/farm-console-unified.html for the target design and the
// capability coverage table that defines "done".
//
// Composition, top to bottom: view bar · units rail + map + scene timeline ·
// block dock. The map never unmounts — selecting, scrubbing and editing all
// happen around it, which is the whole point of the redesign.
//
// `mapnext/` stays untouched for the parallel run. Everything heavy here is
// imported from it; only the shell and the orchestration wiring are this
// module's own. See useFarmConsole.ts for why the wiring is duplicated.
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import type { FeatureCollection, Polygon } from "geojson";

import { listFarms } from "@/api/farms";
import type { ExistingBlock } from "@/lib/aoi/bulk";
import { GridCellPopup } from "@/modules/grid/GridCellPopup";
import { Page } from "@/components/Page";
import { usePrefs } from "@/prefs/PrefsContext";
import { useCapability } from "@/rbac/useCapability";

import { MapCanvas } from "../map/MapCanvas";
import { InactivateConfirmModal } from "../map/InactivateConfirmModal";
import { SignalObservationPanel } from "../map/SignalObservationPanel";
import { BlockDock } from "../mapnext/BlockDock";
import { ViewBar } from "../mapnext/ViewBar";
import { CreateFarmFlow } from "../mapnext/CreateFarmFlow";
import { BulkAoiUploadPanel } from "../mapnext/BulkAoiUploadPanel";
import {
  AutoBlockPanel,
  CreateBlockPanel,
  CreatePivotPanel,
  DrawHintBar,
} from "../mapnext/createFlows";
import { LAST_FARM_KEY } from "../mapnext/constants";
import { CONSOLE_QK } from "./constants";
import { ConsoleUnitsRail } from "./ConsoleUnitsRail";
import { FarmIdentityStrip } from "./FarmIdentityStrip";
import { IndexLegend } from "./IndexLegend";
import { MapDock } from "./MapDock";
import { SceneTimeline } from "./SceneTimeline";
import { SettingsDrawer } from "./SettingsDrawer";
import { useMapFullscreen } from "./useMapFullscreen";
import { useConsoleMutations } from "./useConsoleMutations";
import { useFarmConsole } from "./useFarmConsole";

/** Every in-console link must build off this, never a literal. */
export const CONSOLE_V2_BASE = "/labs/map-v2";

export function FarmConsoleV2Page(): ReactNode {
  const { farmId } = useParams<{ farmId?: string }>();
  const [search] = useSearchParams();
  // Creating a farm is a tenant-level flow: a brand-new tenant has no farm to
  // scope to, so it branches ahead of the console.
  if (search.get("create") === "farm") return <CreateFarmFlow contextFarmId={farmId} />;
  if (!farmId) return <ConsoleV2Redirect />;
  return <Console farmId={farmId} />;
}

/**
 * The live console's own redirect hard-navigates to /labs/map/<id>, which
 * would bounce a v2 visitor straight back to v1. Resolve against this route.
 */
function ConsoleV2Redirect(): ReactNode {
  const navigate = useNavigate();
  const { t } = useTranslation("farmConsole");
  const farmsQ = useQuery({
    queryKey: CONSOLE_QK.farmsList(),
    queryFn: () => listFarms({ limit: 50 }),
    staleTime: 30_000,
  });

  useEffect(() => {
    if (!farmsQ.data) return;
    const last = typeof window !== "undefined" ? window.localStorage.getItem(LAST_FARM_KEY) : null;
    const target = farmsQ.data.items.find((f) => f.id === last) ?? farmsQ.data.items[0];
    if (target) navigate(`${CONSOLE_V2_BASE}/${target.id}`, { replace: true });
  }, [farmsQ.data, navigate]);

  return (
    <div className="grid h-full place-items-center text-sm text-ap-muted">
      {farmsQ.isLoading
        ? t("page.loadingFarms")
        : farmsQ.data && farmsQ.data.items.length === 0
          ? t("page.noFarm")
          : t("page.redirecting")}
    </div>
  );
}

function Console({ farmId }: { farmId: string }): ReactNode {
  const { t } = useTranslation("farmConsole");
  const navigate = useNavigate();
  const { unit: areaUnit } = usePrefs();
  const [, setSearch] = useSearchParams();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const fullscreen = useMapFullscreen<HTMLElement>();
  const canCreateFarm = useCapability("farm.create");
  const canInactivateFarm = useCapability("farm.delete", { farmId });
  const canBulkReplace = useCapability("block.delete", { farmId });

  const flash = (msg: string): void => {
    setToast(msg);
    window.setTimeout(() => setToast((m) => (m === msg ? null : m)), 2600);
  };

  const c = useFarmConsole(farmId);
  const m = useConsoleMutations({
    farmId,
    selectedId: c.selectedId,
    onSelect: c.select,
    onDeselect: c.deselect,
    flash,
  });

  // Existing blocks (code + boundary) for the bulk-upload client classifier.
  const existingBlocks = useMemo<ExistingBlock[]>(() => {
    const out: ExistingBlock[] = [];
    for (const f of c.summaryQ.data?.geojson.features ?? []) {
      const code = c.blocksById.get(f.properties.id)?.code;
      if (code) out.push({ code, geometry: f.geometry });
    }
    return out;
  }, [c.summaryQ.data, c.blocksById]);

  // Preview overlay: the auto-grid candidates currently selected for creation.
  const autoBlockPreviewFc = useMemo<FeatureCollection<Polygon> | null>(() => {
    if (!m.autoOpen || !m.candidates) return null;
    return {
      type: "FeatureCollection",
      features: m.candidates
        .filter((cand) => m.selectedCandidates.has(cand.code))
        .map((cand) => ({
          type: "Feature" as const,
          geometry: cand.boundary,
          properties: { code: cand.code },
        })),
    };
  }, [m.autoOpen, m.candidates, m.selectedCandidates]);

  const startCreateFarm = (): void => {
    // Farm creation lives in its own (non farm-scoped) view — flip the flag in
    // the URL so it survives a reload and the Back button leaves it.
    setSearch((prev) => {
      const next = new URLSearchParams(prev);
      next.set("create", "farm");
      next.delete("unit");
      return next;
    });
  };

  if (c.summaryQ.isLoading) {
    return (
      <div className="grid h-full place-items-center text-sm text-ap-muted">
        {t("page.loading")}
      </div>
    );
  }
  if (c.summaryQ.isError || !c.summaryQ.data) {
    return (
      <div className="grid h-full place-items-center gap-3 text-center text-sm text-ap-muted">
        <p>{t("page.loadError")}</p>
        <button
          type="button"
          onClick={() => void c.summaryQ.refetch()}
          className="rounded-md bg-ap-primary px-3 py-1.5 text-white"
        >
          {t("page.retry")}
        </button>
      </div>
    );
  }

  const summary = c.summaryQ.data;
  const farmName = summary.farm.name;
  const selectedBlock = c.selectedId ? summary.blocks.find((b) => b.id === c.selectedId) : null;
  const reshaping = m.reshapeTarget != null;

  return (
    <Page width="bleed">
      <ViewBar
        activeIndex={c.activeIndex}
        onIndexChange={c.setActiveIndex}
        layers={c.layers}
        onLayersChange={(patch) => c.setLayers((l) => ({ ...l, ...patch }))}
        onOpenSettings={() => setSettingsOpen(true)}
        showGrid={c.showGrid}
        onToggleGrid={() => {
          c.setShowGrid((s) => !s);
          c.setSelectedCellId(null);
        }}
        signalDefs={(c.signalDefsQ.data ?? []).map((d) => ({ id: d.id, name: d.name }))}
        signalDefId={c.signalDefId}
        onSignalDefChange={c.changeSignalDef}
        onAddBlock={m.startDrawBlock}
        onAddPivot={m.startDrawPivot}
        onAutoBlock={m.startAutoBlock}
        onBulkUpload={m.startBulkUpload}
        onAddFarm={canCreateFarm ? startCreateFarm : undefined}
        leading={
          <FarmIdentityStrip
            name={farmName}
            areaM2={summary.farm.area_m2}
            blocks={summary.blocks}
          />
        }
      />

      <div className="flex min-h-0 flex-1">
        <ConsoleUnitsRail
          blocks={summary.blocks}
          summaries={summary.summaries}
          selectedId={c.selectedId}
          onSelect={c.select}
          activeIndex={c.activeIndex}
        />

        {/* Map and dock share one column so the dock spans the map canvas
            only, and follows the rail as it collapses. */}
        <div className="flex min-w-0 flex-1 flex-col">
          <main ref={fullscreen.ref} className="relative min-w-0 flex-1 bg-ap-bg">
            <MapCanvas
              geojson={c.geojsonWithClasses ?? summary.geojson}
              farmBoundary={summary.farm.boundary}
              selectedId={c.selectedId}
              onSelect={c.select}
              fitBoundsKey={farmId}
              showAoi={c.layers.aoi}
              showBlocks={c.layers.blocks}
              showBlockBorders={c.layers.borders}
              showBlockLabels={c.layers.labels}
              borderOpacity={c.layers.borderOpacity}
              blockFillOpacity={c.layers.fillOpacity}
              // The pixels ARE the reading; the cells are reference lines
              // drawn over them, so their fill goes whenever pixels are up.
              pixelLayers={c.showPixels ? c.pixels.layers : null}
              gridFillVisible={false}
              blockFillColorProperty="class_color"
              gridCells={c.gridCellsFc}
              highlightedCellIds={c.highlightedCellIds}
              selectedGridCellId={c.selectedCellId}
              onGridCellClick={(cellId, point) => {
                c.setSelectedCellId(cellId);
                c.setCellClickPoint(point);
              }}
              signalOverlay={c.signalOverlayFc}
              onSignalClick={c.selectObservation}
              reshapeBlock={
                m.reshapeTarget
                  ? { id: m.reshapeTarget.id, boundary: m.reshapeTarget.boundary }
                  : null
              }
              onReshape={(poly) => m.setReshapeCandidate(poly)}
              drawEnabled={m.drawTarget != null && !reshaping}
              drawTarget={m.drawTarget ?? "block"}
              onDrawProgress={m.setDrawProgress}
              onPolygonDrawn={(poly, areaM2, target) => {
                m.setDrawProgress(null);
                if (target === "block") m.setPendingBlock({ polygon: poly, areaM2 });
              }}
              onPivotDrawn={(r) =>
                m.setPendingPivot({ lat: r.center_lat, lon: r.center_lon, radiusM: r.radius_m })
              }
              autoBlockPreview={autoBlockPreviewFc}
              bulkPreview={m.bulkPreviewFc}
            />

            {/* Zone 5 — how am I reading this: view modes, not visibility. */}
            <MapDock
              className="absolute bottom-3 end-3 z-10 bg-ap-panel/95 shadow-card"
              showPixels={c.showPixels}
              pixelsAvailable={c.pixels.assetCount > 0}
              onTogglePixels={() => c.setShowPixels((s) => !s)}
              showGrid={c.showGrid}
              gridAvailable={c.gridded.length > 0}
              onToggleGrid={() => {
                c.setShowGrid((s) => !s);
                c.setSelectedCellId(null);
              }}
              onFullscreen={fullscreen.toggle}
              isFullscreen={fullscreen.isFullscreen}
            />

            {/* Zone 4 — index legend. Anchored to the map's trailing edge so
                it reads against the pixels it describes. */}
            <IndexLegend
              className="absolute end-3 top-3 z-10 w-[268px] bg-ap-panel/95 shadow-card"
              code={c.activeIndex}
              areas={c.pixels.classAreas(c.selectedId)}
              scopeBlockId={c.selectedId}
              scopeBlockName={c.selectedId ? (c.blockNameById.get(c.selectedId) ?? null) : null}
              showPixels={c.showPixels}
              assetCount={c.pixels.assetCount}
              imagerySubCount={c.imagerySubCount}
              loading={c.pixels.assetsLoading || c.pixels.statsLoading}
              onOpenImagerySettings={() => navigate(`/config/imagery/${farmId}`)}
            />

            {/* Draw-in-progress hint (before a shape is completed) */}
            {m.drawTarget && !m.pendingBlock && !m.pendingPivot ? (
              <DrawHintBar
                kind={m.drawTarget}
                vertices={m.drawProgress?.vertices}
                areaM2={m.drawProgress?.areaM2}
                onCancel={m.resetCreate}
              />
            ) : null}

            {m.pendingBlock ? (
              <CreateBlockPanel
                areaM2={m.pendingBlock.areaM2}
                submitting={m.createBlockMut.isPending}
                error={m.createBlockMut.isError ? t("create.createFailed") : null}
                onSubmit={({ code, name }) =>
                  m.createBlockMut.mutate({ polygon: m.pendingBlock!.polygon, code, name })
                }
                onCancel={m.resetCreate}
              />
            ) : null}

            {m.pendingPivot ? (
              <CreatePivotPanel
                centerLat={m.pendingPivot.lat}
                centerLon={m.pendingPivot.lon}
                radiusM={m.pendingPivot.radiusM}
                submitting={m.createPivotMut.isPending}
                error={m.createPivotMut.isError ? t("create.createFailed") : null}
                onSubmit={({ code, name, sector_count }) =>
                  m.createPivotMut.mutate({
                    lat: m.pendingPivot!.lat,
                    lon: m.pendingPivot!.lon,
                    radiusM: m.pendingPivot!.radiusM,
                    code,
                    name,
                    sectorCount: sector_count,
                  })
                }
                onCancel={m.resetCreate}
              />
            ) : null}

            {m.autoOpen ? (
              <AutoBlockPanel
                maxAreaM2={m.maxAreaM2}
                onMaxAreaM2={m.setMaxAreaM2}
                unit={areaUnit}
                effectiveCellSizeM={m.autoCellSizeM}
                onCompute={() => void m.computeAutoGrid()}
                computing={m.autoComputing}
                candidates={m.candidates}
                selected={m.selectedCandidates}
                onToggle={m.toggleCandidate}
                onToggleAll={m.toggleAllCandidates}
                creating={m.autoCreating}
                progressDone={m.autoCreatedCount}
                error={m.autoError}
                onCreate={() => void m.commitAutoBlock()}
                onClose={m.closeAuto}
              />
            ) : null}

            {m.bulkOpen ? (
              <BulkAoiUploadPanel
                farmId={farmId}
                existing={existingBlocks}
                canReplace={canBulkReplace}
                onPreviewChange={m.setBulkPreviewFc}
                onCommitted={({ created, replaced, reused, errors }) => {
                  m.invalidateAll();
                  flash(t("bulk.committed", { created, replaced, reused, errors }));
                }}
                onClose={m.closeBulk}
              />
            ) : null}

            {reshaping ? (
              <div className="absolute start-1/2 top-3.5 z-20 flex -translate-x-1/2 items-center gap-3 rounded-xl bg-ap-panel px-4 py-2 shadow-card rtl:translate-x-1/2">
                <span className="text-sm font-semibold text-ap-ink">{t("page.reshapeTitle")}</span>
                <button
                  type="button"
                  disabled={!m.reshapeCandidate || m.reshapeMut.isPending}
                  onClick={() =>
                    m.reshapeCandidate &&
                    m.reshapeMut.mutate({
                      blockId: m.reshapeTarget!.id,
                      boundary: m.reshapeCandidate,
                    })
                  }
                  className="h-8 rounded-lg bg-ap-primary px-3 text-sm font-semibold text-white disabled:opacity-50"
                >
                  {t("manage.save")}
                </button>
                <button
                  type="button"
                  onClick={m.cancelReshape}
                  className="h-8 rounded-lg border border-ap-line px-3 text-sm font-semibold text-ap-ink"
                >
                  {t("manage.cancel")}
                </button>
              </div>
            ) : null}

            {c.selectedCellId ? (
              <GridCellPopup
                open
                cellId={c.selectedCellId}
                productId={c.cellMeta.get(c.selectedCellId)?.productId ?? null}
                indexCode={c.activeIndex}
                value={c.cellMeta.get(c.selectedCellId)?.value ?? null}
                lat={c.cellMeta.get(c.selectedCellId)?.lat ?? null}
                lon={c.cellMeta.get(c.selectedCellId)?.lon ?? null}
                blockName={c.cellMeta.get(c.selectedCellId)?.blockName ?? null}
                x={c.cellClickPoint?.x ?? null}
                y={c.cellClickPoint?.y ?? null}
                time={c.cellMeta.get(c.selectedCellId)?.time ?? null}
                baselineMean={c.selectedCellBaseline?.blockMean ?? null}
                z={c.selectedCellBaseline?.z ?? null}
                cellItems={c.cellItemsByCell.get(c.selectedCellId) ?? []}
                onClose={() => {
                  c.setSelectedCellId(null);
                  c.setCellClickPoint(null);
                }}
              />
            ) : null}

            {c.selectedObsId ? (
              <SignalObservationPanel
                observation={c.selectedObs}
                definition={c.selectedSignalDef}
                isLoading={c.signalObsQ.isLoading}
                x={c.obsClickPoint?.x ?? null}
                y={c.obsClickPoint?.y ?? null}
                onClose={c.clearObservation}
              />
            ) : null}

            {toast ? (
              <div className="pointer-events-none absolute bottom-4 start-1/2 z-20 -translate-x-1/2 rounded-full bg-ap-ink/85 px-3.5 py-1.5 text-meta text-white shadow-card rtl:translate-x-1/2">
                {toast}
              </div>
            ) : null}

            {/* Inactive-farm banner — the way back from a farm inactivation. */}
            {!summary.farm.is_active ? (
              <div className="absolute bottom-4 end-4 z-20 flex items-center gap-2 rounded-xl bg-ap-warn-soft px-3.5 py-2 text-meta text-ap-ink shadow-card">
                <span>
                  {t("dangerZone.inactiveSince", { date: summary.farm.active_to ?? "—" })}
                </span>
                {canInactivateFarm ? (
                  <button
                    type="button"
                    onClick={() => m.reactivateFarmMut.mutate()}
                    disabled={m.reactivateFarmMut.isPending}
                    className="rounded-lg bg-ap-warn px-2.5 py-1 text-meta font-semibold text-white disabled:opacity-50"
                  >
                    {m.reactivateFarmMut.isPending
                      ? t("dangerZone.reactivating")
                      : t("dangerZone.reactivate")}
                  </button>
                ) : null}
              </div>
            ) : null}
          </main>

          {/* Zone 6 — the time spine. Belongs to the map, not the dock: it
              changes what the map shows, so it sits directly under it and
              spans the map column only. */}
          <SceneTimeline
            scenes={c.scenes}
            selectedDate={c.sceneDate}
            onSelect={c.selectScene}
            medianGapDays={c.medianGapDays}
            loading={c.scenesQ.isLoading}
            available={c.scenesQ.data !== null}
          />

          {c.selectedId ? (
            <BlockDock
              detail={c.detailQ.data}
              integration={c.selectedIntegration}
              loading={c.detailQ.isLoading}
              error={c.detailQ.isError}
              activeIndex={c.activeIndex}
              onActiveIndexChange={c.setActiveIndex}
              onClose={c.deselect}
              farmId={farmId}
              gridProductId={c.gridProductId}
              onReshape={() => void m.openReshape()}
              onInactivate={() => m.setInactivateOpen(true)}
              resetKey={m.resetKey}
            />
          ) : null}
        </div>
      </div>

      {settingsOpen ? (
        <SettingsDrawer
          farmId={farmId}
          farmName={farmName}
          canInactivate={canInactivateFarm}
          onInactivateFarm={() => {
            // The drawer sits above the modal — close it before confirming.
            setSettingsOpen(false);
            m.setInactivateFarmOpen(true);
          }}
          onReactivateFarm={() => m.reactivateFarmMut.mutate()}
          reactivating={m.reactivateFarmMut.isPending}
          reactivateError={m.reactivateFarmMut.isError ? t("dangerZone.reactivateError") : null}
          onClose={() => setSettingsOpen(false)}
        />
      ) : null}

      {m.inactivateOpen && c.selectedId ? (
        <InactivateConfirmModal
          confirmKeyword={selectedBlock?.code ?? "INACTIVATE"}
          entityLabel="block"
          preview={m.inactivatePreviewQ.data ?? null}
          previewError={m.inactivatePreviewQ.isError ? t("page.previewError") : null}
          submitting={m.inactivateMut.isPending}
          submitError={m.inactivateMut.isError ? t("manage.saveError") : null}
          onCancel={() => m.setInactivateOpen(false)}
          onSubmit={(reason) => m.inactivateMut.mutate({ blockId: c.selectedId!, reason })}
        />
      ) : null}

      {m.inactivateFarmOpen ? (
        <InactivateConfirmModal
          confirmKeyword={summary.farm.code}
          entityLabel="farm"
          preview={m.farmInactivatePreviewQ.data ?? null}
          previewError={m.farmInactivatePreviewQ.isError ? t("page.previewError") : null}
          submitting={m.inactivateFarmMut.isPending}
          submitError={m.inactivateFarmMut.isError ? t("manage.saveError") : null}
          onCancel={() => m.setInactivateFarmOpen(false)}
          onSubmit={(reason) => m.inactivateFarmMut.mutate(reason)}
        />
      ) : null}
    </Page>
  );
}

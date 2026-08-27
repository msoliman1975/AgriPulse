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
import { localizedName } from "@/lib/localizedField";
import { GridCellPopup } from "@/modules/grid/GridCellPopup";
import { Page } from "@/components/Page";
import { usePrefs } from "@/prefs/PrefsContext";
import { useCapability } from "@/rbac/useCapability";

import { MapCanvas } from "../map/MapCanvas";
import { MarkerLegend } from "../map/MarkerLegend";
import { InactivateConfirmModal } from "../map/InactivateConfirmModal";
import { FieldFlagPanel } from "../map/FieldFlagPanel";
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
import { LAST_FARM_KEY, MAP_INDEX_ORDER } from "../mapnext/constants";
import { CONSOLE_QK } from "./constants";
import { ConsoleUnitsRail } from "./ConsoleUnitsRail";
import { FarmIdentityStrip } from "./FarmIdentityStrip";
import { IndexLegend } from "./IndexLegend";
import { MapDataControl } from "./MapDataControl";
import { MapLayerBar } from "./MapLayerBar";
import { SceneTimeline } from "./SceneTimeline";
import { SettingsDrawer } from "./SettingsDrawer";
import { useMapFullscreen } from "./useMapFullscreen";
import { useConsoleMutations } from "./useConsoleMutations";
import { TIMELINE_RANGES } from "./timelineWindow";
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
  const { t, i18n } = useTranslation("farmConsole");
  const navigate = useNavigate();
  const { unit: areaUnit } = usePrefs();
  const [, setSearch] = useSearchParams();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [openFlagId, setOpenFlagId] = useState<string | null>(null);
  const [flagClickPoint, setFlagClickPoint] = useState<{ x: number; y: number } | null>(null);
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
  const farmName = localizedName(i18n.language, summary.farm.name, summary.farm.name_ar);
  const selectedBlock = c.selectedId ? summary.blocks.find((b) => b.id === c.selectedId) : null;
  const reshaping = m.reshapeTarget != null;

  // The legend is labelled by the scope it was SERVED, not the one requested.
  // A farm drawn from one stitched surface is measured once for the whole
  // farm, so selecting a block cannot narrow these numbers — and naming the
  // block over farm-wide areas would be a wrong caption on right figures.
  const legendAreas = c.pixels.classAreas(c.selectedId);
  const legendScopeBlockId = legendAreas.scopedToBlock ? c.selectedId : null;

  return (
    <Page width="bleed">
      <ViewBar
        activeIndex={c.activeIndex}
        onIndexChange={c.setActiveIndex}
        // Everything, thermal included: this console paints the index COG
        // itself, and `lst.tif`/`cwsi.tif`/`smi.tif` are written by the same
        // pipeline step that writes `ndvi.tif`.
        indexOptions={MAP_INDEX_ORDER}
        layers={c.layers}
        onLayersChange={(patch) => c.setLayers((l) => ({ ...l, ...patch }))}
        // The `Layers ▾` chip is gone from THIS console: the same switches are
        // picture cards on the map itself (MapLayersControl), and keeping both
        // would give one piece of state two front doors. The live console
        // still renders the chip — it has no cards — which is why this is a
        // prop rather than a deletion inside ViewBar.
        showLayersMenu={false}
        // The index and the signal picker moved onto the map, into the one
        // control that decides what data is drawn. Leaving a copy in the bar
        // would be two front doors onto one piece of state, which is how the
        // old cards and the old rail came to disagree about the mesh.
        showIndexMenu={false}
        showSignalsMenu={false}
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
        // The map's frame — what is outlined, how hard, and what a block is
        // called. Spelled out on the bar rather than hidden behind a chip:
        // these are checkboxes and sliders, and a checkbox behind two clicks
        // is a checkbox nobody finds.
        trailing={
          <MapLayerBar
            layers={c.layers}
            onLayersChange={(patch) => c.setLayers((l) => ({ ...l, ...patch }))}
            showGrid={c.showGrid}
            onToggleGrid={() => {
              c.setShowGrid((sh) => !sh);
              c.setSelectedCellId(null);
            }}
            gridAvailable={c.gridded.length > 0}
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
              geojson={c.geojsonForMap ?? summary.geojson}
              farmBoundary={summary.farm.boundary}
              selectedId={c.selectedId}
              onSelect={c.select}
              fitBoundsKey={farmId}
              showAoi={c.layers.aoi}
              showBlocks={c.layers.blocks}
              showBlockBorders={c.layers.borders}
              showBlockLabels={c.layers.labels}
              blockLabelProperty={c.layers.labelField === "crop" ? "crop_label" : "name"}
              showAlerts={c.layers.alerts}
              borderOpacity={c.layers.borderOpacity}
              blockFillOpacity={c.layers.fillOpacity}
              // The pixels ARE the reading; the cells are reference lines
              // drawn over them, so their fill goes whenever pixels are up.
              pixelLayers={c.showPixels ? c.pixels.layers : null}
              gridFillVisible={false}
              // The flat per-block class colour STANDS IN for the raster; it
              // must not sit on top of one. `units-fill` is a vector layer, so
              // it draws above the pixels at 0.8 opacity — 36 flat rectangles
              // over a single stitched farm surface, which is what "the map
              // draws block by block" looked like on a farm-raster date.
              //
              // So: raster drawn -> no class fill, the pixels are the reading.
              // No raster -> class fill, which is the only reading there is.
              // At "None" the property is absent from every feature anyway, so
              // the blocks come out unfilled and the satellite shows through.
              blockFillColorProperty={
                c.showPixels && c.pixels.assetCount > 0 ? undefined : "class_color"
              }
              gridCells={c.gridCellsFc}
              gridIndexCode={c.activeIndex}
              highlightedCellIds={c.highlightedCellIds}
              selectedGridCellId={c.selectedCellId}
              onGridCellClick={(cellId, point) => {
                c.setSelectedCellId(cellId);
                c.setCellClickPoint(point);
              }}
              signalOverlay={c.signalOverlayFc}
              flagOverlay={c.flagOverlayFc}
              onFlagClick={(flagId, point) => {
                setOpenFlagId(flagId);
                setFlagClickPoint(point);
              }}
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

            {/* Zones 4 and 5 share ONE trailing column.
                They used to be two independent absolute boxes both pinned to
                `end-3`: the legend at the top, the datapoint rail at the
                vertical middle. The legend grows with the index — thirteen
                class rows plus areas — so on any short map it reached the
                middle and sat on top of the rail. A column cannot overlap
                itself: the legend takes the space it needs from the top and
                scrolls when there is not enough, and the rail is pinned to
                the bottom.

                `bottom-8` clears the MapLibre attribution strip. The wrapper
                ignores pointer events so the map is still draggable between
                the two panels; each child takes them back. */}
            <div className="pointer-events-none absolute bottom-8 end-3 top-3 z-10 flex flex-col items-end gap-2">
              {c.selectedIndex ? (
                <IndexLegend
                  className="pointer-events-auto min-h-0 w-[268px] flex-shrink overflow-y-auto bg-ap-panel/95 shadow-card"
                  code={c.selectedIndex}
                  areas={legendAreas}
                  scopeBlockId={legendScopeBlockId}
                  scopeBlockName={
                    legendScopeBlockId ? (c.blockNameById.get(legendScopeBlockId) ?? null) : null
                  }
                  showPixels={c.showPixels}
                  assetCount={c.pixels.assetCount}
                  indexUnit={c.activeIndexUnit}
                  imagerySubCount={c.imagerySubCount}
                  loading={c.pixels.assetsLoading || c.pixels.statsLoading}
                  onOpenImagerySettings={() => navigate(`/config/imagery/${farmId}`)}
                />
              ) : null}

              <div className="flex-1" />

              {/* What data is on the map. One control: the index (its "None"
                  is the pixel off switch), alert chips, field flags, signal
                  readings, the mark legend, and full screen. */}
              <MapDataControl
                className="pointer-events-auto relative flex-none"
                activeIndex={c.selectedIndex}
                indexOptions={MAP_INDEX_ORDER}
                onIndexChange={c.changeSelectedIndex}
                pixelsAvailable={c.pixels.assetCount > 0}
                alerts={c.layers.alerts}
                onAlertsChange={(on) => c.setLayers((l) => ({ ...l, alerts: on }))}
                flagsMode={c.flagsMode}
                onFlagsModeChange={c.changeFlagsMode}
                signalDefs={(c.signalDefsQ.data ?? []).map((d) => ({ id: d.id, name: d.name }))}
                signalsOn={c.layers.signals}
                signalDefId={c.signalDefId}
                onSignalsChange={c.changeSignals}
                markLegend={c.layers.markLegend}
                onMarkLegendChange={(on) => c.setLayers((l) => ({ ...l, markLegend: on }))}
                onFullscreen={fullscreen.toggle}
                isFullscreen={fullscreen.isFullscreen}
              />
            </div>

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
                onSubmit={({ code, name, name_ar }) =>
                  m.createBlockMut.mutate({
                    polygon: m.pendingBlock!.polygon,
                    code,
                    name,
                    name_ar,
                  })
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
                onSubmit={({ code, name, name_ar, sector_count }) =>
                  m.createPivotMut.mutate({
                    lat: m.pendingPivot!.lat,
                    lon: m.pendingPivot!.lon,
                    radiusM: m.pendingPivot!.radiusM,
                    code,
                    name,
                    name_ar,
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
                indexCode={c.gridIndex}
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
                farmHasCellReadings={c.farmHasCellReadings}
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
                stack={c.selectedObsStack}
                onSelectFromStack={c.showObservation}
                asOfDate={c.sceneDate}
                x={c.obsClickPoint?.x ?? null}
                y={c.obsClickPoint?.y ?? null}
                onClose={c.clearObservation}
              />
            ) : null}

            {/* Field flag popup — the thread a supervisor answers in. */}
            {openFlagId ? (
              <FieldFlagPanel
                flagId={openFlagId}
                x={flagClickPoint?.x ?? null}
                y={flagClickPoint?.y ?? null}
                onClose={() => {
                  setOpenFlagId(null);
                  setFlagClickPoint(null);
                }}
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

          {/* What the marks mean — a strip between the map and the date bar,
              off by default and switched from the datapoint control. Here and
              not over the map: it is a reference somebody reads once, and a
              panel floating over the farm costs map every second it is open. */}
          {c.layers.markLegend ? (
            <div className="flex-none border-t border-ap-line bg-ap-panel">
              <MarkerLegend variant="bar" />
            </div>
          ) : null}

          {/* Zone 6 — the time spine. Belongs to the map, not the dock: it
              changes what the map shows, so it sits directly under it and
              spans the map column only. */}
          <SceneTimeline
            scenes={c.visibleScenes}
            allScenes={c.scenes}
            selectedDate={c.sceneDate}
            onSelect={c.selectScene}
            medianGapDays={c.medianGapDays}
            loading={c.scenesQ.isLoading}
            available={c.scenesQ.data !== null}
            rangeDays={c.timelineDays}
            onRangeChange={c.setTimelineDays}
            ranges={TIMELINE_RANGES}
          />

          {c.selectedId ? (
            <BlockDock
              detail={c.detailQ.data}
              integration={c.selectedIntegration}
              loading={c.detailQ.isLoading}
              error={c.detailQ.isError}
              activeIndex={c.activeIndex}
              // The pixel console draws the index raster itself, so every
              // index the dock lists can also be painted from it.
              paintableIndices={MAP_INDEX_ORDER}
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

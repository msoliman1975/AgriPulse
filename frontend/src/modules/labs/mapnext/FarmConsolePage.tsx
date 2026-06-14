// Farm Console — redesigned Farm Management surface (/labs/map-next).
//
// A progressive-disclosure re-take of /labs/map: slim view bar + units
// rail + a two-tier inspector (monitor by default, manage one click away),
// with farm-level config behind a settings drawer. Built as a NEW page so
// it can be iterated and A/B'd before replacing /labs/map. Reuses the
// existing data loaders (loadMapSummary / loadUnitDetail) and MapCanvas.
// See docs/proposals/farm-management-redesign.md.
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import type { FeatureCollection, Polygon } from "geojson";

import { getFarm, listFarms, updateFarm, type FarmUpdatePayload, type WaterSource } from "@/api/farms";
import {
  getBlock,
  getBlockInactivationPreview,
  inactivateBlock,
  updateBlock,
  type Block,
  type BlockDetail,
} from "@/api/blocks";
import { getGridCells } from "@/api/grid";
import { listSubscriptions } from "@/api/imagery";
import type { IndexCode as ApiIndexCode } from "@/api/indices";
import { listSignalDefinitions, listSignalObservations } from "@/api/signals";
import { loadMapSummary, loadUnitDetail } from "../map/api";
import { MapCanvas, type GridCellProps } from "../map/MapCanvas";
import { GridCellPopup } from "@/modules/grid/GridCellPopup";
import { InactivateConfirmModal } from "../map/InactivateConfirmModal";
import { SignalObservationPanel } from "../map/SignalObservationPanel";
import { buildSignalOverlay, blockCentroidsFromGeojson } from "../map/signalOverlay";
import { FarmDefaultsTab } from "../map/FarmDefaultsTab";
import { FarmMembersTab } from "../map/FarmMembersTab";
import { Inspector } from "./Inspector";
import { UnitsRail } from "./UnitsRail";
import { ViewBar, type LayerState } from "./ViewBar";

const LAST_FARM_KEY = "labs/map/lastFarm";

export function FarmConsolePage(): ReactNode {
  const { farmId } = useParams<{ farmId?: string }>();
  if (!farmId) return <FarmRedirect />;
  return <Console farmId={farmId} />;
}

function FarmRedirect(): ReactNode {
  const navigate = useNavigate();
  const { t } = useTranslation("farmConsole");
  const farmsQ = useQuery({
    queryKey: ["labs/mapnext/farmsList"],
    queryFn: () => listFarms({ limit: 50 }),
    staleTime: 30_000,
  });
  useEffect(() => {
    if (!farmsQ.data) return;
    const last = typeof window !== "undefined" ? window.localStorage.getItem(LAST_FARM_KEY) : null;
    const target = farmsQ.data.items.find((f) => f.id === last) ?? farmsQ.data.items[0];
    if (target) navigate(`/labs/map/${target.id}`, { replace: true });
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
  const [search, setSearch] = useSearchParams();
  const selectedId = search.get("unit");

  const qc = useQueryClient();
  // One index drives both the map grid overlay and the inspector featured card.
  const [activeIndex, setActiveIndex] = useState<ApiIndexCode>("ndvi");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [layers, setLayers] = useState<LayerState>({
    aoi: true,
    blocks: true,
    borders: true,
    labels: true,
    borderOpacity: 0.6,
    fillOpacity: 1,
  });
  // Grid overlay
  const [showGrid, setShowGrid] = useState(false);
  const [selectedCellId, setSelectedCellId] = useState<string | null>(null);
  const [cellClickPoint, setCellClickPoint] = useState<{ x: number; y: number } | null>(null);
  // Signal observation overlay
  const [signalDefId, setSignalDefId] = useState<string | null>(null);
  const [obsClickPoint, setObsClickPoint] = useState<{ x: number; y: number } | null>(null);
  const selectedObsId = search.get("signal_obs");
  // Reshape + inactivate (page-level: need the map / a modal)
  const [reshapeTarget, setReshapeTarget] = useState<BlockDetail | null>(null);
  const [reshapeCandidate, setReshapeCandidate] = useState<Polygon | null>(null);
  const [inactivateOpen, setInactivateOpen] = useState(false);
  const [resetKey, setResetKey] = useState(0);

  useEffect(() => {
    if (typeof window !== "undefined") window.localStorage.setItem(LAST_FARM_KEY, farmId);
  }, [farmId]);

  const summaryQ = useQuery({
    queryKey: ["labs/mapnext/summary", farmId],
    queryFn: () => loadMapSummary(farmId),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });

  const blocksById = useMemo(() => {
    const m = new Map<string, Block>();
    for (const b of summaryQ.data?.blocks ?? []) m.set(b.id, b);
    return m;
  }, [summaryQ.data]);
  const blockNameById = useMemo(() => {
    const m = new Map<string, string>();
    for (const b of summaryQ.data?.blocks ?? []) m.set(b.id, b.name?.trim() || b.code);
    return m;
  }, [summaryQ.data]);

  const detailQ = useQuery({
    queryKey: ["labs/mapnext/detail", farmId, selectedId],
    queryFn: () =>
      loadUnitDetail({
        farmId,
        blockId: selectedId as string,
        blocksById,
        activePlan: summaryQ.data?.activePlan,
        blockHealth: selectedId ? summaryQ.data?.blockHealth[selectedId] : null,
      }),
    enabled: Boolean(selectedId && blocksById.size > 0),
    staleTime: 30_000,
  });

  // First active imagery product for the selected block — needed for grid config.
  const subsQ = useQuery({
    queryKey: ["labs/mapnext/subs", selectedId],
    queryFn: () => listSubscriptions(selectedId as string, { include_inactive: false }),
    enabled: Boolean(selectedId),
    staleTime: 60_000,
  });
  const gridProductId = subsQ.data?.[0]?.product_id ?? null;

  // Farm-wide grid: no farm-level cells endpoint, so fan out per gridded block
  // (each via its first active subscription) and merge client-side. Lazy.
  const overlayBlocks = summaryQ.data?.blocks ?? [];
  const overlayKey = overlayBlocks.map((b) => b.id).join(",");
  const farmGridQ = useQuery({
    queryKey: ["labs/mapnext/farmGrid", farmId, activeIndex, overlayKey],
    queryFn: async () => {
      const groups = await Promise.all(
        overlayBlocks.map(async (b) => {
          const subs = await listSubscriptions(b.id, { include_inactive: false });
          const productId = subs[0]?.product_id;
          if (!productId) return null;
          const res = await getGridCells(b.id, productId, activeIndex);
          return { blockId: b.id, productId, cells: res.cells };
        }),
      );
      return groups.filter((g): g is NonNullable<typeof g> => g !== null);
    },
    enabled: Boolean(showGrid && overlayBlocks.length > 0),
    staleTime: 30_000,
  });

  const gridCellsFc: FeatureCollection<Polygon, GridCellProps> | null = useMemo(() => {
    if (!showGrid || !farmGridQ.data) return null;
    return {
      type: "FeatureCollection",
      features: farmGridQ.data.flatMap((g) =>
        g.cells.map((c) => ({
          type: "Feature" as const,
          geometry: c.geometry,
          properties: { cell_id: c.cell_id, value: c.mean === null ? -1 : Number(c.mean) },
        })),
      ),
    };
  }, [showGrid, farmGridQ.data]);

  // cellId -> meta (block, product, location, value, time) for the popup.
  const cellMeta = useMemo(() => {
    const m = new Map<
      string,
      { blockId: string; productId: string; lat: number; lon: number; value: number | null; time: string | null; blockName: string }
    >();
    for (const g of farmGridQ.data ?? []) {
      for (const c of g.cells) {
        m.set(c.cell_id, {
          blockId: g.blockId,
          productId: g.productId,
          lat: c.centroid_lat,
          lon: c.centroid_lon,
          value: c.mean === null ? null : Number(c.mean),
          time: c.time,
          blockName: blockNameById.get(g.blockId) ?? g.blockId,
        });
      }
    }
    return m;
  }, [farmGridQ.data, blockNameById]);

  // Worst-N (lowest mean) cells → outline on the map.
  const highlightedCellIds = useMemo<string[]>(() => {
    if (!showGrid) return [];
    return (farmGridQ.data ?? [])
      .flatMap((g) => g.cells)
      .filter((c) => c.mean !== null)
      .sort((a, b) => Number(a.mean) - Number(b.mean))
      .slice(0, 5)
      .map((c) => c.cell_id);
  }, [showGrid, farmGridQ.data]);

  // Block-average baseline + z for the selected cell (positive z = BELOW avg).
  const selectedCellBaseline = useMemo(() => {
    if (!selectedCellId) return null;
    const meta = cellMeta.get(selectedCellId);
    if (!meta || meta.value == null) return null;
    const group = farmGridQ.data?.find((g) => g.blockId === meta.blockId);
    const vals = (group?.cells ?? []).map((c) => (c.mean === null ? null : Number(c.mean))).filter((v): v is number => v != null);
    if (vals.length < 2) return null;
    const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
    const variance = vals.reduce((a, b) => a + (b - mean) ** 2, 0) / vals.length;
    const std = Math.sqrt(variance);
    return { blockMean: mean, z: std > 0 ? (mean - meta.value) / std : 0 };
  }, [selectedCellId, cellMeta, farmGridQ.data]);

  // Signal overlay: definitions for the picker + observations for the active one.
  const signalDefsQ = useQuery({
    queryKey: ["labs/mapnext/signalDefs"],
    queryFn: () => listSignalDefinitions(),
    staleTime: 5 * 60_000,
  });
  const signalObsQ = useQuery({
    queryKey: ["labs/mapnext/signalObs", farmId, signalDefId],
    queryFn: () => listSignalObservations({ farm_id: farmId, signal_definition_id: signalDefId ?? undefined, limit: 500 }),
    enabled: Boolean(farmId && signalDefId),
    staleTime: 30_000,
  });
  const selectedSignalDef = signalDefsQ.data?.find((d) => d.id === signalDefId) ?? null;
  const blockCentroids = useMemo(
    () => (summaryQ.data ? blockCentroidsFromGeojson(summaryQ.data.geojson) : new Map<string, [number, number]>()),
    [summaryQ.data],
  );
  const signalOverlayFc = useMemo(() => {
    if (!signalDefId) return null;
    if (!signalObsQ.data) return { type: "FeatureCollection" as const, features: [] };
    return buildSignalOverlay(signalObsQ.data, blockCentroids, { valueKind: selectedSignalDef?.value_kind ?? null }).features;
  }, [signalDefId, signalObsQ.data, blockCentroids, selectedSignalDef]);
  const selectedObs = useMemo(
    () => (selectedObsId && signalObsQ.data ? (signalObsQ.data.find((o) => o.id === selectedObsId) ?? null) : null),
    [selectedObsId, signalObsQ.data],
  );

  const select = (id: string) => {
    const next = new URLSearchParams(search);
    next.set("unit", id);
    next.delete("signal_obs");
    setSearch(next, { replace: false });
    setSelectedCellId(null);
  };
  const deselect = () => {
    const next = new URLSearchParams(search);
    next.delete("unit");
    setSearch(next, { replace: false });
  };

  const flash = (msg: string) => {
    setToast(msg);
    window.setTimeout(() => setToast((m) => (m === msg ? null : m)), 2600);
  };

  // Reshape: load the full block, enter map direct-select, commit on save.
  const openReshape = async () => {
    if (!selectedId) return;
    try {
      const block = await getBlock(selectedId);
      setReshapeTarget(block);
      setReshapeCandidate(null);
      flash(t("page.reshapeHint"));
    } catch {
      /* noop */
    }
  };
  const reshapeMut = useMutation({
    mutationFn: ({ blockId, boundary }: { blockId: string; boundary: Polygon }) => updateBlock(blockId, { boundary }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["labs/mapnext/summary"] });
      void qc.invalidateQueries({ queryKey: ["labs/mapnext/detail"] });
      setReshapeTarget(null);
      setReshapeCandidate(null);
      setResetKey((k) => k + 1);
    },
  });

  // Inactivate
  const inactivatePreviewQ = useQuery({
    queryKey: ["labs/mapnext/inactivatePreview", selectedId],
    queryFn: () => getBlockInactivationPreview(selectedId as string),
    enabled: Boolean(inactivateOpen && selectedId),
  });
  const inactivateMut = useMutation({
    mutationFn: ({ blockId, reason }: { blockId: string; reason: string }) => inactivateBlock(blockId, { reason }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["labs/mapnext/summary"] });
      setInactivateOpen(false);
      deselect();
    },
  });

  if (summaryQ.isLoading) {
    return <div className="grid h-full place-items-center text-sm text-ap-muted">{t("page.loading")}</div>;
  }
  if (summaryQ.isError || !summaryQ.data) {
    return (
      <div className="grid h-full place-items-center gap-3 text-center text-sm text-ap-muted">
        <p>{t("page.loadError")}</p>
        <button type="button" onClick={() => summaryQ.refetch()} className="rounded-md bg-ap-primary px-3 py-1.5 text-white">
          {t("page.retry")}
        </button>
      </div>
    );
  }

  const summary = summaryQ.data;
  const farmName = summary.farm.name;
  const selectedBlock = selectedId ? summary.blocks.find((b) => b.id === selectedId) : null;
  const reshaping = reshapeTarget != null;

  return (
    <div className="flex h-full flex-col">
      <ViewBar
        farmId={farmId}
        activeIndex={activeIndex}
        onIndexChange={setActiveIndex}
        layers={layers}
        onLayersChange={(patch) => setLayers((l) => ({ ...l, ...patch }))}
        onOpenSettings={() => setSettingsOpen(true)}
        showGrid={showGrid}
        onToggleGrid={() => {
          setShowGrid((s) => !s);
          setSelectedCellId(null);
        }}
        signalDefs={(signalDefsQ.data ?? []).map((d) => ({ id: d.id, name: d.name }))}
        signalDefId={signalDefId}
        onSignalDefChange={(id) => {
          setSignalDefId(id);
          const next = new URLSearchParams(search);
          next.delete("signal_obs");
          setSearch(next, { replace: true });
        }}
      />

      <div className="flex min-h-0 flex-1">
        <UnitsRail blocks={summary.blocks} summaries={summary.summaries} selectedId={selectedId} onSelect={select} />

        <main className="relative min-w-0 flex-1">
          <MapCanvas
            geojson={summary.geojson}
            farmBoundary={summary.farm.boundary}
            selectedId={selectedId}
            onSelect={select}
            fitBoundsKey={farmId}
            showAoi={layers.aoi}
            showBlocks={layers.blocks}
            showBlockBorders={layers.borders}
            showBlockLabels={layers.labels}
            borderOpacity={layers.borderOpacity}
            blockFillOpacity={layers.fillOpacity}
            gridCells={gridCellsFc}
            highlightedCellIds={highlightedCellIds}
            selectedGridCellId={selectedCellId}
            onGridCellClick={(cellId, point) => {
              setSelectedCellId(cellId);
              setCellClickPoint(point);
            }}
            signalOverlay={signalOverlayFc}
            onSignalClick={(observationId, point) => {
              const next = new URLSearchParams(search);
              next.set("signal_obs", observationId);
              setSearch(next, { replace: true });
              setObsClickPoint(point);
              setSelectedCellId(null);
            }}
            reshapeBlock={reshapeTarget ? { id: reshapeTarget.id, boundary: reshapeTarget.boundary } : null}
            onReshape={(poly) => setReshapeCandidate(poly)}
          />

          {/* Reshape banner */}
          {reshaping ? (
            <div className="absolute left-1/2 top-3.5 z-20 flex -translate-x-1/2 items-center gap-3 rounded-xl bg-ap-panel px-4 py-2 shadow-card">
              <span className="text-sm font-semibold text-ap-ink">{t("page.reshapeTitle")}</span>
              <button
                type="button"
                disabled={!reshapeCandidate || reshapeMut.isPending}
                onClick={() => reshapeCandidate && reshapeMut.mutate({ blockId: reshapeTarget.id, boundary: reshapeCandidate })}
                className="h-8 rounded-lg bg-ap-primary px-3 text-sm font-semibold text-white disabled:opacity-50"
              >
                {t("manage.save")}
              </button>
              <button
                type="button"
                onClick={() => {
                  setReshapeTarget(null);
                  setReshapeCandidate(null);
                }}
                className="h-8 rounded-lg border border-ap-line px-3 text-sm font-semibold text-ap-ink"
              >
                {t("manage.cancel")}
              </button>
            </div>
          ) : null}

          {/* Grid cell popup */}
          {selectedCellId ? (
            <GridCellPopup
              open
              cellId={selectedCellId}
              productId={cellMeta.get(selectedCellId)?.productId ?? null}
              indexCode={activeIndex}
              value={cellMeta.get(selectedCellId)?.value ?? null}
              lat={cellMeta.get(selectedCellId)?.lat ?? null}
              lon={cellMeta.get(selectedCellId)?.lon ?? null}
              blockName={cellMeta.get(selectedCellId)?.blockName ?? null}
              x={cellClickPoint?.x ?? null}
              y={cellClickPoint?.y ?? null}
              time={cellMeta.get(selectedCellId)?.time ?? null}
              baselineMean={selectedCellBaseline?.blockMean ?? null}
              z={selectedCellBaseline?.z ?? null}
              onClose={() => {
                setSelectedCellId(null);
                setCellClickPoint(null);
              }}
            />
          ) : null}

          {/* Signal observation popup */}
          {selectedObsId ? (
            <SignalObservationPanel
              observation={selectedObs}
              definition={selectedSignalDef}
              isLoading={signalObsQ.isLoading}
              x={obsClickPoint?.x ?? null}
              y={obsClickPoint?.y ?? null}
              onClose={() => {
                const next = new URLSearchParams(search);
                next.delete("signal_obs");
                setSearch(next, { replace: true });
                setObsClickPoint(null);
              }}
            />
          ) : null}

          {toast ? (
            <div className="pointer-events-none absolute bottom-4 left-1/2 z-20 -translate-x-1/2 rounded-full bg-ap-ink/85 px-3.5 py-1.5 text-xs text-white shadow-card">
              {toast}
            </div>
          ) : null}
        </main>

        {selectedId ? (
          <aside className="w-[372px] flex-none border-s border-ap-line">
            <Inspector
              detail={detailQ.data}
              loading={detailQ.isLoading}
              error={detailQ.isError}
              activeIndex={activeIndex}
              onActiveIndexChange={setActiveIndex}
              onClose={deselect}
              farmId={farmId}
              gridProductId={gridProductId}
              onReshape={() => void openReshape()}
              onInactivate={() => setInactivateOpen(true)}
              resetKey={resetKey}
            />
          </aside>
        ) : null}
      </div>

      {settingsOpen ? <SettingsDrawer farmId={farmId} farmName={farmName} onClose={() => setSettingsOpen(false)} /> : null}

      {inactivateOpen && selectedId ? (
        <InactivateConfirmModal
          confirmKeyword={selectedBlock?.code ?? "INACTIVATE"}
          entityLabel="block"
          preview={inactivatePreviewQ.data ?? null}
          previewError={inactivatePreviewQ.isError ? t("page.previewError") : null}
          submitting={inactivateMut.isPending}
          submitError={inactivateMut.isError ? t("manage.saveError") : null}
          onCancel={() => setInactivateOpen(false)}
          onSubmit={(reason) => inactivateMut.mutate({ blockId: selectedId, reason })}
        />
      ) : null}
    </div>
  );
}

// Farm-level config (rare, manager-only). Native panels: block defaults +
// members reuse the existing tab components; the Farm tab is a compact form.
// One quiet entry point off the daily surface.
type SettingsTab = "defaults" | "members" | "farm";

function SettingsDrawer({
  farmId,
  farmName,
  onClose,
}: {
  farmId: string;
  farmName: string;
  onClose: () => void;
}): ReactNode {
  const { t } = useTranslation("farmConsole");
  const [tab, setTab] = useState<SettingsTab>("defaults");
  const tabs: { id: SettingsTab; label: string }[] = [
    { id: "defaults", label: t("settings.tabDefaults") },
    { id: "members", label: t("settings.tabMembers") },
    { id: "farm", label: t("settings.tabFarm") },
  ];
  return (
    <>
      <button type="button" aria-label="Close settings" className="fixed inset-0 z-[90] bg-ap-ink/30" onClick={onClose} />
      <aside className="fixed inset-y-0 end-0 z-[100] flex w-[560px] max-w-[94vw] flex-col bg-ap-panel shadow-2xl">
        <div className="flex items-center gap-3 border-b border-ap-line px-5 py-4">
          <span className="text-xl">⚙</span>
          <div>
            <h2 className="text-lg font-bold text-ap-ink">{t("settings.title")}</h2>
            <div className="text-xs text-ap-muted">{farmName}</div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="ms-auto grid h-8 w-8 place-items-center rounded-lg text-ap-muted hover:bg-ap-line/50"
            aria-label="Close"
          >
            ✕
          </button>
        </div>
        <div className="flex gap-1 border-b border-ap-line px-4 pt-2.5">
          {tabs.map((tb) => (
            <button
              key={tb.id}
              type="button"
              onClick={() => setTab(tb.id)}
              className={
                "rounded-t-lg border-b-2 px-3.5 py-2 text-sm font-semibold " +
                (tab === tb.id ? "border-ap-primary text-ap-primary" : "border-transparent text-ap-muted hover:text-ap-ink")
              }
            >
              {tb.label}
            </button>
          ))}
        </div>
        <div className="flex-1 overflow-auto p-5">
          {tab === "defaults" ? <FarmDefaultsTab farmId={farmId} /> : null}
          {tab === "members" ? <FarmMembersTab farmId={farmId} /> : null}
          {tab === "farm" ? <FarmEditTab farmId={farmId} /> : null}
        </div>
      </aside>
    </>
  );
}

const settingsInput =
  "w-full rounded-lg border border-ap-line bg-ap-panel px-3 py-2 text-sm text-ap-ink focus:border-ap-primary focus:outline-none";
const WATER_SOURCES: WaterSource[] = ["well", "canal", "nile", "desalinated", "rainfed", "mixed"];

function FarmEditTab({ farmId }: { farmId: string }): ReactNode {
  const { t } = useTranslation("farmConsole");
  const navigate = useNavigate();
  const qc = useQueryClient();
  const farmQ = useQuery({ queryKey: ["labs/mapnext/farm", farmId], queryFn: () => getFarm(farmId), staleTime: 30_000 });
  const [form, setForm] = useState<FarmUpdatePayload | null>(null);
  const f = farmQ.data;
  const state: FarmUpdatePayload =
    form ??
    (f
      ? {
          name: f.name,
          governorate: f.governorate,
          district: f.district,
          nearest_city: f.nearest_city,
          primary_water_source: f.primary_water_source,
          tags: f.tags,
        }
      : {});
  const set = (patch: Partial<FarmUpdatePayload>) => setForm({ ...state, ...patch });
  const mut = useMutation({
    mutationFn: (patch: FarmUpdatePayload) => updateFarm(farmId, patch),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["labs/mapnext/summary"] });
      void qc.invalidateQueries({ queryKey: ["labs/mapnext/farm", farmId] });
      void qc.invalidateQueries({ queryKey: ["labs/mapnext/farmsList"] });
    },
  });
  if (farmQ.isLoading) return <div className="text-sm text-ap-muted">{t("inspector.loading")}</div>;
  if (farmQ.isError || !f) return <div className="text-sm text-ap-crit">{t("manage.editLoadError")}</div>;
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        mut.mutate(state);
      }}
    >
      <label className="mb-3 block">
        <span className="mb-1 block text-xs font-semibold text-ap-muted">{t("settingsFarm.name")}</span>
        <input className={settingsInput} value={state.name ?? ""} onChange={(e) => set({ name: e.target.value })} />
      </label>
      <div className="grid grid-cols-2 gap-3">
        <label className="mb-3 block">
          <span className="mb-1 block text-xs font-semibold text-ap-muted">{t("settingsFarm.governorate")}</span>
          <input className={settingsInput} value={state.governorate ?? ""} onChange={(e) => set({ governorate: e.target.value || null })} />
        </label>
        <label className="mb-3 block">
          <span className="mb-1 block text-xs font-semibold text-ap-muted">{t("settingsFarm.district")}</span>
          <input className={settingsInput} value={state.district ?? ""} onChange={(e) => set({ district: e.target.value || null })} />
        </label>
        <label className="mb-3 block">
          <span className="mb-1 block text-xs font-semibold text-ap-muted">{t("settingsFarm.city")}</span>
          <input className={settingsInput} value={state.nearest_city ?? ""} onChange={(e) => set({ nearest_city: e.target.value || null })} />
        </label>
        <label className="mb-3 block">
          <span className="mb-1 block text-xs font-semibold text-ap-muted">{t("settingsFarm.water")}</span>
          <select className={settingsInput} value={state.primary_water_source ?? ""} onChange={(e) => set({ primary_water_source: (e.target.value || null) as WaterSource | null })}>
            <option value="">—</option>
            {WATER_SOURCES.map((w) => <option key={w} value={w}>{w}</option>)}
          </select>
        </label>
      </div>
      <label className="mb-3 block">
        <span className="mb-1 block text-xs font-semibold text-ap-muted">{t("manage.tags")}</span>
        <input className={settingsInput} value={(state.tags ?? []).join(", ")} onChange={(e) => set({ tags: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })} />
      </label>
      {mut.isError ? <div className="mb-2 text-xs text-ap-crit">{t("manage.saveError")}</div> : null}
      <div className="flex items-center gap-2">
        <button type="submit" disabled={mut.isPending} className="h-9 rounded-lg bg-ap-primary px-4 text-sm font-semibold text-white disabled:opacity-60">
          {mut.isPending ? t("manage.saving") : t("manage.save")}
        </button>
        {mut.isSuccess && !form ? <span className="text-xs text-ap-good">{t("settingsFarm.saved")}</span> : null}
        <button
          type="button"
          onClick={() => navigate(`/labs/map-legacy/${farmId}`)}
          className="ms-auto text-xs text-ap-muted underline hover:text-ap-ink"
        >
          {t("settingsFarm.editAoi")}
        </button>
      </div>
    </form>
  );
}

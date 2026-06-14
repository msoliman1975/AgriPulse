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

import { listFarms } from "@/api/farms";
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
import { loadMapSummary, loadUnitDetail } from "../map/api";
import { MapCanvas, type GridCellProps } from "../map/MapCanvas";
import { GridCellPopup } from "@/modules/grid/GridCellPopup";
import { InactivateConfirmModal } from "../map/InactivateConfirmModal";
import type { IndexCode } from "../map/types";
import { Inspector } from "./Inspector";
import { UnitsRail } from "./UnitsRail";
import { ViewBar, type LayerState } from "./ViewBar";

const LAST_FARM_KEY = "labs/map/lastFarm";
// Every index the grid pipeline stores per cell (sub-block resolution).
const GRID_INDEX_OPTIONS: ApiIndexCode[] = ["ndvi", "ndre", "ndwi", "evi", "savi", "gndvi", "ndmi"];

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
    if (target) navigate(`/labs/map-next/${target.id}`, { replace: true });
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
  const [activeIndex, setActiveIndex] = useState<IndexCode>("ndvi");
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
  const [gridIndex, setGridIndex] = useState<ApiIndexCode>("ndvi");
  const [selectedCellId, setSelectedCellId] = useState<string | null>(null);
  const [cellClickPoint, setCellClickPoint] = useState<{ x: number; y: number } | null>(null);
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
    queryKey: ["labs/mapnext/farmGrid", farmId, gridIndex, overlayKey],
    queryFn: async () => {
      const groups = await Promise.all(
        overlayBlocks.map(async (b) => {
          const subs = await listSubscriptions(b.id, { include_inactive: false });
          const productId = subs[0]?.product_id;
          if (!productId) return null;
          const res = await getGridCells(b.id, productId, gridIndex);
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

  const select = (id: string) => {
    const next = new URLSearchParams(search);
    next.set("unit", id);
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
        gridIndex={gridIndex}
        onGridIndexChange={setGridIndex}
        gridIndexOptions={GRID_INDEX_OPTIONS}
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
            reshapeBlock={reshapeTarget ? { id: reshapeTarget.id, boundary: reshapeTarget.boundary } : null}
            onReshape={(poly) => setReshapeCandidate(poly)}
          />

          {/* Reshape banner */}
          {reshaping ? (
            <div className="absolute left-1/2 top-3.5 z-20 flex -translate-x-1/2 items-center gap-3 rounded-xl bg-ap-panel px-4 py-2 shadow-card">
              <span className="text-[13px] font-semibold text-ap-ink">{t("page.reshapeTitle")}</span>
              <button
                type="button"
                disabled={!reshapeCandidate || reshapeMut.isPending}
                onClick={() => reshapeCandidate && reshapeMut.mutate({ blockId: reshapeTarget.id, boundary: reshapeCandidate })}
                className="h-8 rounded-lg bg-ap-primary px-3 text-[13px] font-semibold text-white disabled:opacity-50"
              >
                {t("manage.save")}
              </button>
              <button
                type="button"
                onClick={() => {
                  setReshapeTarget(null);
                  setReshapeCandidate(null);
                }}
                className="h-8 rounded-lg border border-ap-line px-3 text-[13px] font-semibold text-ap-ink"
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
              indexCode={gridIndex}
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

          {toast ? (
            <div className="pointer-events-none absolute bottom-4 left-1/2 z-20 -translate-x-1/2 rounded-full bg-ap-ink/85 px-3.5 py-1.5 text-[12.5px] text-white shadow-card">
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
              onScout={() => flash(t("page.scoutToast"))}
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

// Farm-level config (rare, manager-only) — for v1 this drawer deep-links
// into the existing, fully-built config pages rather than re-implementing
// them. The redesign value is the IA: one quiet entry point off the daily
// surface. Native panels can replace these links in a later iteration.
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
  const navigate = useNavigate();
  const go = (path: string) => {
    onClose();
    navigate(path);
  };
  const Item = ({ icon, title, desc, path }: { icon: string; title: string; desc: string; path: string }) => (
    <button
      type="button"
      onClick={() => go(path)}
      className="flex w-full items-start gap-3 rounded-xl border border-ap-line bg-ap-panel p-3.5 text-start hover:bg-ap-primary-soft"
    >
      <span className="text-lg leading-none">{icon}</span>
      <span className="flex-1">
        <span className="block text-[14px] font-semibold text-ap-ink">{title}</span>
        <span className="block text-[12px] text-ap-muted">{desc}</span>
      </span>
      <span className="text-ap-muted">›</span>
    </button>
  );
  return (
    <>
      <button
        type="button"
        aria-label="Close settings"
        className="fixed inset-0 z-[90] bg-ap-ink/30"
        onClick={onClose}
      />
      <aside className="fixed inset-y-0 end-0 z-[100] flex w-[480px] max-w-[92vw] flex-col bg-ap-panel shadow-2xl">
        <div className="flex items-center gap-3 border-b border-ap-line px-5 py-4">
          <span className="text-xl">⚙</span>
          <div>
            <h2 className="text-lg font-bold text-ap-ink">{t("settings.title")}</h2>
            <div className="text-[12px] text-ap-muted">{farmName}</div>
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
        <div className="flex-1 space-y-3 overflow-auto p-5">
          <div className="rounded-xl border border-ap-primary-soft bg-ap-primary-soft/40 p-3 text-[12.5px] text-ap-primary">
            {t("settings.note")}
          </div>
          <Item icon="🛰️" title={t("settings.defaults")} desc={t("settings.defaultsDesc")} path={`/config/imagery/${farmId}`} />
          <Item icon="👥" title={t("settings.members")} desc={t("settings.membersDesc")} path={`/farms/${farmId}/members`} />
          <Item icon="🌾" title={t("settings.farm")} desc={t("settings.farmDesc")} path={`/farms/${farmId}/edit`} />
        </div>
      </aside>
    </>
  );
}

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import {
  createBlock,
  createPivot,
  getBlock,
  getBlockInactivationPreview,
  inactivateBlock,
  listBlocks,
  reactivateBlock,
  updateBlock,
  type Block,
  type BlockDetail,
  type BlockInactivationPreview,
  type BlockUpdatePayload,
} from "@/api/blocks";
import {
  createFarm,
  getFarmInactivationPreview,
  inactivateFarm,
  listFarms,
  reactivateFarm,
  updateFarm,
  type FarmCreatePayload,
  type FarmInactivationPreview,
  type FarmUpdatePayload,
} from "@/api/farms";
import { loadMapSummary, loadUnitDetail } from "./api";
import { MapCanvas, type DrawTarget } from "./MapCanvas";
import { DetailPanel } from "./DetailPanel";
import { DrawBlockModal, type DrawBlockFormValues } from "./DrawBlockModal";
import { CreatePivotModal } from "./CreatePivotModal";
import { InactivateConfirmModal } from "./InactivateConfirmModal";
import { FarmDrawer, type FarmDrawerMode } from "./FarmDrawer";
import { FarmSummaryStrip } from "./FarmSummaryStrip";
import type { MultiPolygon, Polygon } from "geojson";

const SUMMARY_POLL_MS = 60_000;

const DRAWER_WIDTH_STORAGE_KEY = "labs.map.drawer.width";
const DRAWER_MIN_PX = 380;
const DRAWER_MAX_PX = 720;
const DRAWER_DEFAULT_FRACTION = 1 / 3;

const LAYER_PREFS_STORAGE_KEY = "labs.map.layer.prefs";
const LAST_FARM_STORAGE_KEY = "labs.map.last_farm";

interface LayerPrefs {
  aoi: boolean;
  borders: boolean;
  labels: boolean;
  borderOpacity: number; // 0..1
}

const DEFAULT_LAYER_PREFS: LayerPrefs = {
  aoi: true,
  borders: true,
  labels: true,
  borderOpacity: 0.9,
};

function loadLayerPrefs(): LayerPrefs {
  if (typeof window === "undefined") return DEFAULT_LAYER_PREFS;
  const raw = window.localStorage.getItem(LAYER_PREFS_STORAGE_KEY);
  if (!raw) return DEFAULT_LAYER_PREFS;
  try {
    const parsed = JSON.parse(raw) as Partial<LayerPrefs>;
    return {
      aoi: parsed.aoi ?? DEFAULT_LAYER_PREFS.aoi,
      borders: parsed.borders ?? DEFAULT_LAYER_PREFS.borders,
      labels: parsed.labels ?? DEFAULT_LAYER_PREFS.labels,
      borderOpacity:
        typeof parsed.borderOpacity === "number"
          ? Math.max(0.1, Math.min(1, parsed.borderOpacity))
          : DEFAULT_LAYER_PREFS.borderOpacity,
    };
  } catch {
    return DEFAULT_LAYER_PREFS;
  }
}

function clampDrawerWidth(px: number): number {
  return Math.min(DRAWER_MAX_PX, Math.max(DRAWER_MIN_PX, Math.round(px)));
}

function loadStoredDrawerWidth(): number | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(DRAWER_WIDTH_STORAGE_KEY);
  if (!raw) return null;
  const n = Number(raw);
  return Number.isFinite(n) ? clampDrawerWidth(n) : null;
}

// ---------- No-farmId entry: redirect to the user's last farm ---------------

function FarmPickerRedirect() {
  const navigate = useNavigate();
  const farmsQ = useQuery({
    queryKey: ["labs/map/farmsList"],
    queryFn: () => listFarms({ limit: 50 }),
    staleTime: 30_000,
  });

  useEffect(() => {
    if (!farmsQ.data) return;
    const last =
      typeof window !== "undefined"
        ? window.localStorage.getItem(LAST_FARM_STORAGE_KEY)
        : null;
    const target =
      farmsQ.data.items.find((f) => f.id === last) ?? farmsQ.data.items[0];
    if (target) navigate(`/labs/map/${target.id}`, { replace: true });
  }, [farmsQ.data, navigate]);

  if (farmsQ.isLoading) return <FullState>Loading farms…</FullState>;
  if (farmsQ.isError) {
    return (
      <FullState>
        <p>Couldn't load farms.</p>
      </FullState>
    );
  }
  if (farmsQ.data && farmsQ.data.items.length === 0) {
    return (
      <FullState>
        <p>You don't have a farm yet — create one to begin.</p>
      </FullState>
    );
  }
  return <FullState>Redirecting…</FullState>;
}

// ---------- Main page -------------------------------------------------------

export function MapExperiencePage() {
  const { farmId } = useParams<{ farmId?: string }>();
  if (!farmId) return <FarmPickerRedirect />;
  return <MapForFarm farmId={farmId} />;
}

function MapForFarm({ farmId }: { farmId: string }) {
  const [search, setSearch] = useSearchParams();
  const selectedId = search.get("unit");
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  // Remember which farm the user was on for the redirect helper.
  useEffect(() => {
    window.localStorage.setItem(LAST_FARM_STORAGE_KEY, farmId);
  }, [farmId]);

  // ---- Drawer width (persisted) ------------------------------------------

  const [drawerWidth, setDrawerWidth] = useState<number>(() => {
    const stored = loadStoredDrawerWidth();
    if (stored) return stored;
    if (typeof window === "undefined") return DRAWER_MIN_PX;
    return clampDrawerWidth(window.innerWidth * DRAWER_DEFAULT_FRACTION);
  });
  useEffect(() => {
    window.localStorage.setItem(DRAWER_WIDTH_STORAGE_KEY, String(drawerWidth));
  }, [drawerWidth]);

  // ---- Layer prefs --------------------------------------------------------

  const [layerPrefs, setLayerPrefs] = useState<LayerPrefs>(() => loadLayerPrefs());
  useEffect(() => {
    window.localStorage.setItem(LAYER_PREFS_STORAGE_KEY, JSON.stringify(layerPrefs));
  }, [layerPrefs]);

  // ---- Drawing state (shared between block + farm-AOI draw modes) --------

  // null = idle; "block" = draw-block toggle; "farm_aoi" = drawing AOI from
  // the farm drawer. The MapCanvas takes whichever target is active when
  // the user finishes a polygon.
  const [drawTarget, setDrawTarget] = useState<DrawTarget | null>(null);

  // Block-create state — after a polygon is finalized, the form modal
  // collects code/name/irrigation.
  const [pendingBlockPolygon, setPendingBlockPolygon] = useState<Polygon | null>(
    null,
  );
  const [pendingBlockArea, setPendingBlockArea] = useState<number>(0);

  // Farm-AOI state — captures the polygon that's been drawn for the farm
  // drawer to consume. Wrapped into a MultiPolygon at submit time.
  const [pendingFarmAoi, setPendingFarmAoi] = useState<MultiPolygon | null>(null);
  const [pendingFarmAoiAreaM2, setPendingFarmAoiAreaM2] = useState<number | null>(
    null,
  );

  // Pivot-create state — captured when the user finishes the click-center +
  // click-radius interaction. Modal collects code/name/sector_count.
  const [pendingPivot, setPendingPivot] = useState<{
    lat: number;
    lon: number;
    radius_m: number;
  } | null>(null);

  // Block-edit state — the full Block record is loaded lazily so we have
  // every field (including ones not on the slim summary projection).
  const [editingBlock, setEditingBlock] = useState<BlockDetail | null>(null);

  // Reshape state — the block we're reshaping + the candidate polygon
  // emitted by the map.
  const [reshapeTarget, setReshapeTarget] = useState<BlockDetail | null>(null);
  const [reshapeCandidate, setReshapeCandidate] = useState<Polygon | null>(null);

  // ---- Farm drawer state --------------------------------------------------

  const [farmDrawerMode, setFarmDrawerMode] = useState<FarmDrawerMode | null>(null);

  // ---- Inactivate flows ---------------------------------------------------

  const [inactivateBlockOpen, setInactivateBlockOpen] = useState(false);
  const [inactivateBlockPreview, setInactivateBlockPreview] =
    useState<BlockInactivationPreview | null>(null);
  const [inactivateBlockPreviewError, setInactivateBlockPreviewError] =
    useState<string | null>(null);

  const [inactivateFarmOpen, setInactivateFarmOpen] = useState(false);
  const [inactivateFarmPreview, setInactivateFarmPreview] =
    useState<FarmInactivationPreview | null>(null);
  const [inactivateFarmPreviewError, setInactivateFarmPreviewError] = useState<
    string | null
  >(null);

  // ---- Data queries -------------------------------------------------------

  const summaryQ = useQuery({
    queryKey: ["labs/map/summary", farmId],
    queryFn: () => loadMapSummary(farmId),
    enabled: Boolean(farmId),
    refetchInterval: SUMMARY_POLL_MS,
    staleTime: 30_000,
  });

  // Inactive blocks for the Archive section.
  const inactiveBlocksQ = useQuery({
    queryKey: ["labs/map/inactiveBlocks", farmId],
    queryFn: async () => {
      const page = await listBlocks(farmId, { include_inactive: true, limit: 200 });
      return page.items.filter((b) => !b.is_active);
    },
    enabled: Boolean(farmId) && farmDrawerMode !== null,
    staleTime: 30_000,
  });

  // Farm picker dropdown source.
  const farmsListQ = useQuery({
    queryKey: ["labs/map/farmsList"],
    queryFn: () => listFarms({ limit: 50 }),
    staleTime: 60_000,
  });

  const blocksById = useMemo(() => {
    const m = new Map<string, NonNullable<typeof summaryQ.data>["blocks"][number]>();
    for (const b of summaryQ.data?.blocks ?? []) m.set(b.id, b);
    return m;
  }, [summaryQ.data]);

  const detailQ = useQuery({
    queryKey: ["labs/map/detail", farmId, selectedId],
    queryFn: () =>
      loadUnitDetail({
        farmId,
        blockId: selectedId!,
        blocksById,
        activePlan: summaryQ.data?.activePlan ?? null,
        blockHealth: selectedId ? summaryQ.data?.blockHealth[selectedId] ?? null : null,
      }),
    enabled: Boolean(farmId && selectedId && blocksById.size > 0),
    staleTime: 30_000,
  });

  // ---- Selection helpers --------------------------------------------------

  function selectUnit(id: string) {
    const next = new URLSearchParams(search);
    next.set("unit", id);
    setSearch(next, { replace: false });
  }
  function closePanel() {
    const next = new URLSearchParams(search);
    next.delete("unit");
    setSearch(next, { replace: false });
  }

  // ---- Mutations ----------------------------------------------------------

  const createBlockMut = useMutation({
    mutationFn: async (vars: { polygon: Polygon; values: DrawBlockFormValues }) =>
      createBlock(farmId, {
        code: vars.values.code,
        name: vars.values.name || null,
        boundary: vars.polygon,
        irrigation_system: vars.values.irrigation_system,
        unit_type: "block",
      }),
    onSuccess: (newBlock) => {
      queryClient.invalidateQueries({ queryKey: ["labs/map/summary", farmId] });
      setDrawTarget(null);
      setPendingBlockPolygon(null);
      setPendingBlockArea(0);
      selectUnit(newBlock.id);
    },
  });

  const inactivateBlockMut = useMutation({
    mutationFn: async (vars: { blockId: string; reason: string }) =>
      inactivateBlock(vars.blockId, { reason: vars.reason }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["labs/map/summary", farmId] });
      queryClient.invalidateQueries({ queryKey: ["labs/map/inactiveBlocks", farmId] });
      setInactivateBlockOpen(false);
      setInactivateBlockPreview(null);
      setInactivateBlockPreviewError(null);
      closePanel();
    },
  });

  const updateBlockMut = useMutation({
    mutationFn: (vars: { blockId: string; patch: BlockUpdatePayload }) =>
      updateBlock(vars.blockId, vars.patch),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["labs/map/summary", farmId] });
      queryClient.invalidateQueries({ queryKey: ["labs/map/detail", farmId, selectedId] });
      setEditingBlock(null);
      setReshapeTarget(null);
      setReshapeCandidate(null);
    },
  });

  async function openEditBlock() {
    if (!selectedId) return;
    try {
      const block = await getBlock(selectedId);
      setEditingBlock(block);
    } catch {
      // Surface noisily through the existing detail-load query path.
    }
  }

  async function openReshapeBlock() {
    if (!selectedId) return;
    try {
      const block = await getBlock(selectedId);
      setReshapeTarget(block);
      setReshapeCandidate(null);
    } catch {
      /* noop */
    }
  }

  const createPivotMut = useMutation({
    mutationFn: async (vars: {
      center: { lat: number; lon: number };
      radius_m: number;
      code: string;
      name: string;
      sector_count: number;
    }) =>
      createPivot(farmId, {
        code: vars.code,
        name: vars.name || null,
        center: vars.center,
        radius_m: vars.radius_m,
        sector_count: vars.sector_count,
      }),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["labs/map/summary", farmId] });
      setPendingPivot(null);
      setDrawTarget(null);
      selectUnit(result.pivot.id);
    },
  });

  const reactivateBlockMut = useMutation({
    mutationFn: (blockId: string) => reactivateBlock(blockId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["labs/map/summary", farmId] });
      queryClient.invalidateQueries({ queryKey: ["labs/map/inactiveBlocks", farmId] });
    },
  });

  const createFarmMut = useMutation({
    mutationFn: (payload: FarmCreatePayload) => createFarm(payload),
    onSuccess: (newFarm) => {
      queryClient.invalidateQueries({ queryKey: ["labs/map/farmsList"] });
      setFarmDrawerMode(null);
      setPendingFarmAoi(null);
      setPendingFarmAoiAreaM2(null);
      navigate(`/labs/map/${newFarm.id}`, { replace: false });
    },
  });

  const updateFarmMut = useMutation({
    mutationFn: (payload: FarmUpdatePayload) => updateFarm(farmId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["labs/map/summary", farmId] });
      queryClient.invalidateQueries({ queryKey: ["labs/map/farmsList"] });
      setFarmDrawerMode("view");
      setPendingFarmAoi(null);
      setPendingFarmAoiAreaM2(null);
    },
  });

  const inactivateFarmMut = useMutation({
    mutationFn: (reason: string) => inactivateFarm(farmId, { reason }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["labs/map/farmsList"] });
      setInactivateFarmOpen(false);
      setInactivateFarmPreview(null);
      setInactivateFarmPreviewError(null);
      setFarmDrawerMode(null);
      // Navigate away because the farm is now hidden.
      navigate("/labs/map", { replace: true });
    },
  });

  const reactivateFarmMut = useMutation({
    mutationFn: () => reactivateFarm(farmId, { restore_blocks: true }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["labs/map/summary", farmId] });
      queryClient.invalidateQueries({ queryKey: ["labs/map/farmsList"] });
    },
  });

  // ---- Inactivate-flow openers -------------------------------------------

  async function openInactivateBlock() {
    if (!selectedId) return;
    setInactivateBlockOpen(true);
    setInactivateBlockPreview(null);
    setInactivateBlockPreviewError(null);
    try {
      const data = await getBlockInactivationPreview(selectedId);
      setInactivateBlockPreview(data);
    } catch (err) {
      setInactivateBlockPreviewError(
        err instanceof Error ? err.message : "Failed to load preview",
      );
    }
  }

  async function openInactivateFarm() {
    setInactivateFarmOpen(true);
    setInactivateFarmPreview(null);
    setInactivateFarmPreviewError(null);
    try {
      const data = await getFarmInactivationPreview(farmId);
      setInactivateFarmPreview(data);
    } catch (err) {
      setInactivateFarmPreviewError(
        err instanceof Error ? err.message : "Failed to load preview",
      );
    }
  }

  // ---- Drawer resize ------------------------------------------------------

  const dragStateRef = useRef<{ startX: number; startWidth: number } | null>(null);
  const onResizeMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      dragStateRef.current = { startX: e.clientX, startWidth: drawerWidth };

      const onMove = (ev: MouseEvent) => {
        if (!dragStateRef.current) return;
        const dx = dragStateRef.current.startX - ev.clientX;
        setDrawerWidth(clampDrawerWidth(dragStateRef.current.startWidth + dx));
      };
      const onUp = () => {
        dragStateRef.current = null;
        window.removeEventListener("mousemove", onMove);
        window.removeEventListener("mouseup", onUp);
      };
      window.addEventListener("mousemove", onMove);
      window.addEventListener("mouseup", onUp);
    },
    [drawerWidth],
  );

  // ---- Render -------------------------------------------------------------

  if (summaryQ.isLoading) {
    return <FullState>Loading farm map…</FullState>;
  }
  if (summaryQ.isError || !summaryQ.data) {
    return (
      <FullState>
        <p>Couldn't load map.</p>
        <button
          type="button"
          onClick={() => summaryQ.refetch()}
          className="mt-2 rounded bg-slate-900 px-3 py-1 text-xs text-white"
        >
          Retry
        </button>
      </FullState>
    );
  }

  const summary = summaryQ.data;
  const noUnits = summary.geojson.features.length === 0;
  const drawing = drawTarget !== null;
  const inactiveBlocks: Block[] = inactiveBlocksQ.data ?? [];

  return (
    <div
      className="-mx-4 -my-6 flex flex-col"
      style={{ height: "calc(100vh - 56px)" }}
    >
      <Toolbar
        farmName={summary.farm.name}
        drawTarget={drawTarget}
        onToggleDrawBlock={() =>
          setDrawTarget((cur) => (cur === "block" ? null : "block"))
        }
        onToggleDrawPivot={() =>
          setDrawTarget((cur) => (cur === "pivot" ? null : "pivot"))
        }
        layerPrefs={layerPrefs}
        onLayerPrefsChange={setLayerPrefs}
        farmsList={farmsListQ.data?.items ?? []}
        currentFarmId={farmId}
        onSwitchFarm={(id) => {
          if (id === farmId) return;
          navigate(`/labs/map/${id}`);
        }}
        onCreateFarm={() => {
          setPendingFarmAoi(null);
          setPendingFarmAoiAreaM2(null);
          setFarmDrawerMode("create");
        }}
      />

      <FarmSummaryStrip
        farm={summary.farm}
        onOpenDrawer={() => setFarmDrawerMode("view")}
      />

      <div className="relative flex-1 overflow-hidden">
        {noUnits && !drawing ? (
          <FullState>
            <p>This farm has no operational units defined yet.</p>
            <button
              type="button"
              onClick={() => setDrawTarget("block")}
              className="mt-3 rounded bg-slate-900 px-3 py-1 text-xs text-white"
            >
              Draw a block to get started
            </button>
          </FullState>
        ) : (
          <MapCanvas
            geojson={summary.geojson}
            farmBoundary={summary.farm.boundary}
            selectedId={selectedId}
            onSelect={selectUnit}
            fitBoundsKey={farmId}
            drawEnabled={drawing}
            drawTarget={drawTarget ?? "block"}
            onPolygonDrawn={(poly, areaM2, target) => {
              if (target === "block") {
                setPendingBlockPolygon(poly);
                setPendingBlockArea(areaM2);
              } else if (target === "farm_aoi") {
                setPendingFarmAoi({
                  type: "MultiPolygon",
                  coordinates: [poly.coordinates],
                });
                setPendingFarmAoiAreaM2(areaM2);
                setDrawTarget(null);
              }
            }}
            onPivotDrawn={(r) => {
              setPendingPivot({
                lat: r.center_lat,
                lon: r.center_lon,
                radius_m: r.radius_m,
              });
            }}
            reshapeBlock={
              reshapeTarget
                ? { id: reshapeTarget.id, boundary: reshapeTarget.boundary }
                : null
            }
            onReshape={(poly) => setReshapeCandidate(poly)}
            showAoi={layerPrefs.aoi}
            showBlockBorders={layerPrefs.borders}
            showBlockLabels={layerPrefs.labels}
            borderOpacity={layerPrefs.borderOpacity}
          />
        )}

        <MapNote drawTarget={drawTarget} />

        {selectedId && farmDrawerMode === null ? (
          <DetailPanel
            detail={detailQ.data ?? null}
            isLoading={detailQ.isLoading}
            onClose={closePanel}
            width={drawerWidth}
            onResizeMouseDown={onResizeMouseDown}
            onInactivate={openInactivateBlock}
            editableBlock={editingBlock}
            onStartEdit={openEditBlock}
            onCancelEdit={() => setEditingBlock(null)}
            onSaveEdit={(patch) =>
              updateBlockMut.mutate({ blockId: selectedId, patch })
            }
            saving={updateBlockMut.isPending}
            saveError={updateBlockMut.error?.message ?? null}
            reshaping={reshapeTarget?.id === selectedId}
            onStartReshape={openReshapeBlock}
            onSaveReshape={() => {
              if (!reshapeTarget || !reshapeCandidate) return;
              updateBlockMut.mutate({
                blockId: reshapeTarget.id,
                patch: { boundary: reshapeCandidate },
              });
            }}
            onCancelReshape={() => {
              setReshapeTarget(null);
              setReshapeCandidate(null);
            }}
            reshapeSaving={updateBlockMut.isPending}
          />
        ) : null}

        {pendingPivot ? (
          <CreatePivotModal
            centerLat={pendingPivot.lat}
            centerLon={pendingPivot.lon}
            radiusM={pendingPivot.radius_m}
            submitting={createPivotMut.isPending}
            errorMessage={createPivotMut.error?.message ?? null}
            onCancel={() => setPendingPivot(null)}
            onSubmit={(vals) =>
              createPivotMut.mutate({
                center: { lat: pendingPivot.lat, lon: pendingPivot.lon },
                radius_m: pendingPivot.radius_m,
                code: vals.code,
                name: vals.name,
                sector_count: vals.sector_count,
              })
            }
          />
        ) : null}

        {pendingBlockPolygon ? (
          <DrawBlockModal
            polygonAreaM2={pendingBlockArea}
            submitting={createBlockMut.isPending}
            errorMessage={createBlockMut.error?.message ?? null}
            onCancel={() => {
              setPendingBlockPolygon(null);
              setPendingBlockArea(0);
            }}
            onSubmit={(values) =>
              createBlockMut.mutate({ polygon: pendingBlockPolygon, values })
            }
          />
        ) : null}

        {farmDrawerMode ? (
          <FarmDrawer
            mode={farmDrawerMode}
            farm={
              farmDrawerMode === "create"
                ? null
                : summary.farm
            }
            inactiveBlocks={inactiveBlocks}
            draftBoundary={pendingFarmAoi}
            draftAreaM2={pendingFarmAoiAreaM2}
            width={drawerWidth}
            drawingAoi={drawTarget === "farm_aoi"}
            submitting={createFarmMut.isPending || updateFarmMut.isPending}
            submitError={
              createFarmMut.error?.message ?? updateFarmMut.error?.message ?? null
            }
            onClose={() => {
              setFarmDrawerMode(null);
              setPendingFarmAoi(null);
              setPendingFarmAoiAreaM2(null);
              setDrawTarget(null);
            }}
            onModeChange={setFarmDrawerMode}
            onStartDrawAoi={() => setDrawTarget("farm_aoi")}
            onCancelDrawAoi={() => setDrawTarget(null)}
            onSubmitCreate={(payload) => createFarmMut.mutate(payload)}
            onSubmitUpdate={(payload) => updateFarmMut.mutate(payload)}
            onInactivateFarm={openInactivateFarm}
            onReactivateBlock={(blockId) => reactivateBlockMut.mutate(blockId)}
            onResizeMouseDown={onResizeMouseDown}
          />
        ) : null}

        {inactivateBlockOpen && selectedId ? (
          <InactivateConfirmModal
            confirmKeyword={
              summary.blocks.find((b) => b.id === selectedId)?.code ?? "INACTIVATE"
            }
            entityLabel="block"
            preview={inactivateBlockPreview}
            previewError={inactivateBlockPreviewError}
            submitting={inactivateBlockMut.isPending}
            submitError={inactivateBlockMut.error?.message ?? null}
            onCancel={() => {
              setInactivateBlockOpen(false);
              setInactivateBlockPreview(null);
              setInactivateBlockPreviewError(null);
            }}
            onSubmit={(reason) =>
              inactivateBlockMut.mutate({ blockId: selectedId, reason })
            }
          />
        ) : null}

        {inactivateFarmOpen ? (
          <InactivateConfirmModal
            confirmKeyword={summary.farm.code}
            entityLabel="farm"
            preview={inactivateFarmPreview}
            previewError={inactivateFarmPreviewError}
            submitting={inactivateFarmMut.isPending}
            submitError={inactivateFarmMut.error?.message ?? null}
            onCancel={() => {
              setInactivateFarmOpen(false);
              setInactivateFarmPreview(null);
              setInactivateFarmPreviewError(null);
            }}
            onSubmit={(reason) => inactivateFarmMut.mutate(reason)}
          />
        ) : null}

        {!summary.farm.is_active ? (
          <div className="pointer-events-auto absolute bottom-3 right-3 z-10 rounded-md bg-amber-50 px-3 py-2 text-[11px] text-amber-900 shadow">
            Farm inactive (since {summary.farm.active_to}).
            <button
              type="button"
              onClick={() => reactivateFarmMut.mutate()}
              disabled={reactivateFarmMut.isPending}
              className="ms-2 rounded bg-amber-700 px-2 py-0.5 text-[10px] font-medium text-white disabled:opacity-50"
            >
              Reactivate (with blocks)
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}

// ---------- Sub-components --------------------------------------------------

function Toolbar({
  farmName,
  drawTarget,
  onToggleDrawBlock,
  onToggleDrawPivot,
  layerPrefs,
  onLayerPrefsChange,
  farmsList,
  currentFarmId,
  onSwitchFarm,
  onCreateFarm,
}: {
  farmName: string;
  drawTarget: DrawTarget | null;
  onToggleDrawBlock: () => void;
  onToggleDrawPivot: () => void;
  layerPrefs: LayerPrefs;
  onLayerPrefsChange: (next: LayerPrefs) => void;
  farmsList: { id: string; code: string; name: string }[];
  currentFarmId: string;
  onSwitchFarm: (id: string) => void;
  onCreateFarm: () => void;
}) {
  return (
    <header className="flex h-10 items-center justify-between border-b border-slate-200 bg-white px-3">
      <div className="flex items-center gap-2 text-[13px] font-medium text-slate-800">
        <span aria-hidden>🌱</span>
        <FarmSwitcher
          farmsList={farmsList}
          currentFarmId={currentFarmId}
          farmName={farmName}
          onSwitchFarm={onSwitchFarm}
          onCreateFarm={onCreateFarm}
        />
        <span className="ms-2 rounded bg-amber-100 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-amber-800">
          Lab
        </span>
      </div>
      <div className="flex items-center gap-3 text-[12px] text-slate-500">
        <LayerToggle
          label="AOI"
          checked={layerPrefs.aoi}
          onChange={(v) => onLayerPrefsChange({ ...layerPrefs, aoi: v })}
        />
        <LayerToggle
          label="Borders"
          checked={layerPrefs.borders}
          onChange={(v) => onLayerPrefsChange({ ...layerPrefs, borders: v })}
        />
        <LayerToggle
          label="Labels"
          checked={layerPrefs.labels}
          onChange={(v) => onLayerPrefsChange({ ...layerPrefs, labels: v })}
        />
        <label className="flex items-center gap-1" title="Border opacity">
          <span className="text-[10px] text-slate-500">Opacity</span>
          <input
            type="range"
            min={10}
            max={100}
            step={5}
            value={Math.round(layerPrefs.borderOpacity * 100)}
            onChange={(e) =>
              onLayerPrefsChange({
                ...layerPrefs,
                borderOpacity: Number(e.target.value) / 100,
              })
            }
            className="h-1 w-20 cursor-pointer"
            aria-label="Border opacity"
          />
        </label>
        <span className="text-slate-300">|</span>
        <Swatch color="#97C459" label="Healthy" />
        <Swatch color="#EF9F27" label="Watch" />
        <Swatch color="#E24B4A" label="Critical" />
        <button
          type="button"
          onClick={onToggleDrawBlock}
          className={`ms-2 rounded px-2 py-0.5 text-[11px] font-medium ${
            drawTarget === "block"
              ? "bg-slate-900 text-white"
              : "border border-slate-300 text-slate-700 hover:bg-slate-50"
          }`}
        >
          {drawTarget === "block" ? "Exit draw" : "Draw block"}
        </button>
        <button
          type="button"
          onClick={onToggleDrawPivot}
          className={`rounded px-2 py-0.5 text-[11px] font-medium ${
            drawTarget === "pivot"
              ? "bg-slate-900 text-white"
              : "border border-slate-300 text-slate-700 hover:bg-slate-50"
          }`}
        >
          {drawTarget === "pivot" ? "Exit pivot" : "Draw pivot"}
        </button>
      </div>
    </header>
  );
}

function FarmSwitcher({
  farmsList,
  currentFarmId,
  farmName,
  onSwitchFarm,
  onCreateFarm,
}: {
  farmsList: { id: string; code: string; name: string }[];
  currentFarmId: string;
  farmName: string;
  onSwitchFarm: (id: string) => void;
  onCreateFarm: () => void;
}) {
  // Native <select> for keyboard/a11y; "+ new" routes through onCreateFarm.
  return (
    <select
      aria-label="Select farm"
      value={currentFarmId}
      onChange={(e) => {
        if (e.target.value === "__new__") onCreateFarm();
        else onSwitchFarm(e.target.value);
      }}
      className="rounded border border-slate-300 bg-white px-1.5 py-0.5 text-[12px] font-medium text-slate-800"
    >
      {farmsList.length === 0 ? (
        <option value={currentFarmId}>{farmName}</option>
      ) : (
        farmsList.map((f) => (
          <option key={f.id} value={f.id}>
            {f.code} — {f.name}
          </option>
        ))
      )}
      <option value="__new__">+ New farm…</option>
    </select>
  );
}

function LayerToggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-center gap-1 text-[11px]">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-3 w-3 cursor-pointer"
      />
      {label}
    </label>
  );
}

function Swatch({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1">
      <span
        className="inline-block h-2.5 w-2.5 rounded-sm"
        style={{ backgroundColor: color }}
      />
      {label}
    </span>
  );
}

function MapNote({ drawTarget }: { drawTarget: DrawTarget | null }) {
  return (
    <div
      className="pointer-events-none absolute bottom-2 left-2 rounded bg-white/70 p-1.5 text-[10px] text-slate-700"
      aria-hidden
    >
      {drawTarget === "block" ? (
        <div>
          <strong>Drawing block</strong> · click to add vertices ·{" "}
          <strong>double-click</strong> to finish
        </div>
      ) : drawTarget === "farm_aoi" ? (
        <div>
          <strong>Drawing farm AOI</strong> · click to add vertices ·{" "}
          <strong>double-click</strong> to finish
        </div>
      ) : drawTarget === "pivot" ? (
        <div>
          <strong>Drawing pivot</strong> · click center · move to set radius ·{" "}
          click to confirm · <strong>Esc</strong> cancels
        </div>
      ) : (
        <div>
          <strong>Click</strong> any solid unit ·{" "}
          <strong>click</strong> an index to expand chart
        </div>
      )}
    </div>
  );
}

function FullState({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-full w-full items-center justify-center bg-slate-50 p-6 text-center text-sm text-slate-600">
      <div>{children}</div>
    </div>
  );
}

// Re-export the redirect handler to keep this file the single entry point.
export { FarmPickerRedirect };

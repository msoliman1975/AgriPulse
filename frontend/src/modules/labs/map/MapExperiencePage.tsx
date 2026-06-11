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
import { MapCanvas, type DrawProgress, type DrawTarget, type GridCellProps } from "./MapCanvas";
import { SignalObservationPanel } from "./SignalObservationPanel";
import { getGridCells, type GridWorstCell } from "@/api/grid";
import { listSubscriptions } from "@/api/imagery";
import type { IndexCode } from "@/api/indices";
import { BlockGridConfigCard } from "@/modules/grid/BlockGridConfigCard";
import { GridCellPopup } from "@/modules/grid/GridCellPopup";
import type { FeatureCollection, Polygon as GeoPolygon } from "geojson";
import { blockCentroidsFromGeojson, buildSignalOverlay } from "./signalOverlay";
import {
  listSignalDefinitions,
  listSignalObservations,
  type SignalDefinition,
} from "@/api/signals";
import { DetailPanel } from "./DetailPanel";
import { DrawBlockModal, type DrawBlockFormValues } from "./DrawBlockModal";
import { CreatePivotModal } from "./CreatePivotModal";
import { DrawReadout } from "./DrawReadout";
import { InactivateConfirmModal } from "./InactivateConfirmModal";
import { FarmDrawer, type FarmDrawerMode, type FarmPanel } from "./FarmDrawer";
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
  showBlocks: boolean;
  borders: boolean;
  labels: boolean;
  borderOpacity: number; // 0..1
  blockFillOpacity: number; // 0..1
}

const DEFAULT_LAYER_PREFS: LayerPrefs = {
  aoi: true,
  showBlocks: true,
  borders: true,
  labels: true,
  borderOpacity: 0.9,
  blockFillOpacity: 1,
};

function loadLayerPrefs(): LayerPrefs {
  if (typeof window === "undefined") return DEFAULT_LAYER_PREFS;
  const raw = window.localStorage.getItem(LAYER_PREFS_STORAGE_KEY);
  if (!raw) return DEFAULT_LAYER_PREFS;
  try {
    const parsed = JSON.parse(raw) as Partial<LayerPrefs>;
    return {
      aoi: parsed.aoi ?? DEFAULT_LAYER_PREFS.aoi,
      showBlocks: parsed.showBlocks ?? DEFAULT_LAYER_PREFS.showBlocks,
      borders: parsed.borders ?? DEFAULT_LAYER_PREFS.borders,
      labels: parsed.labels ?? DEFAULT_LAYER_PREFS.labels,
      borderOpacity:
        typeof parsed.borderOpacity === "number"
          ? Math.max(0.1, Math.min(1, parsed.borderOpacity))
          : DEFAULT_LAYER_PREFS.borderOpacity,
      blockFillOpacity:
        typeof parsed.blockFillOpacity === "number"
          ? Math.max(0, Math.min(1, parsed.blockFillOpacity))
          : DEFAULT_LAYER_PREFS.blockFillOpacity,
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
      typeof window !== "undefined" ? window.localStorage.getItem(LAST_FARM_STORAGE_KEY) : null;
    const target = farmsQ.data.items.find((f) => f.id === last) ?? farmsQ.data.items[0];
    if (target) navigate(`/labs/map/${target.id}`, { replace: true });
  }, [farmsQ.data, navigate]);

  if (farmsQ.isLoading) return <FullState>Loading farms…</FullState>;
  if (farmsQ.isError) {
    return (
      <FullState>
        <p>Couldn&apos;t load farms.</p>
      </FullState>
    );
  }
  if (farmsQ.data && farmsQ.data.items.length === 0) {
    return (
      <FullState>
        <p>You don&apos;t have a farm yet — create one to begin.</p>
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
  const [drawProgress, setDrawProgress] = useState<DrawProgress | null>(null);

  // Block-create state — after a polygon is finalized, the form modal
  // collects code/name/irrigation.
  const [pendingBlockPolygon, setPendingBlockPolygon] = useState<Polygon | null>(null);
  const [pendingBlockArea, setPendingBlockArea] = useState<number>(0);

  // Farm-AOI state — captures the polygon that's been drawn for the farm
  // drawer to consume. Wrapped into a MultiPolygon at submit time.
  const [pendingFarmAoi, setPendingFarmAoi] = useState<MultiPolygon | null>(null);
  const [pendingFarmAoiAreaM2, setPendingFarmAoiAreaM2] = useState<number | null>(null);

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

  // ---- Farm details panel state -------------------------------------------
  //
  // Renders as a horizontal panel between the toolbar and the map (not a
  // right-edge drawer any more). User spec: "if user clicks a block while
  // farm panel is opened, the app closes the panel first" — so we auto-
  // close whenever a block becomes selected.
  const [farmDrawerMode, setFarmDrawerMode] = useState<FarmDrawerMode | null>(null);
  const [farmPanel, setFarmPanel] = useState<FarmPanel>("details");
  useEffect(() => {
    if (selectedId && farmDrawerMode !== null) {
      setFarmDrawerMode(null);
      setFarmPanel("details");
      setPendingFarmAoi(null);
      setPendingFarmAoiAreaM2(null);
    }
  }, [selectedId, farmDrawerMode]);

  // ---- Signal overlay state (CS-8) ---------------------------------------
  //
  // Null = no overlay shown. When set to a definition id, the page
  // fetches that signal's observations for the active farm and
  // converts them to a Point FeatureCollection MapCanvas can render.
  const [signalOverlayDefId, setSignalOverlayDefId] = useState<string | null>(null);

  // ---- Inactivate flows ---------------------------------------------------

  const [inactivateBlockOpen, setInactivateBlockOpen] = useState(false);
  const [inactivateBlockPreview, setInactivateBlockPreview] =
    useState<BlockInactivationPreview | null>(null);
  const [inactivateBlockPreviewError, setInactivateBlockPreviewError] = useState<string | null>(
    null,
  );

  const [inactivateFarmOpen, setInactivateFarmOpen] = useState(false);
  const [inactivateFarmPreview, setInactivateFarmPreview] =
    useState<FarmInactivationPreview | null>(null);
  const [inactivateFarmPreviewError, setInactivateFarmPreviewError] = useState<string | null>(null);

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

  // CS-8: signal definitions list (powers the overlay picker).
  // Tenant-scoped; one fetch covers the whole session. Cached 5 min.
  const signalDefinitionsQ = useQuery({
    queryKey: ["labs/map/signalDefinitions"],
    queryFn: () => listSignalDefinitions(),
    staleTime: 5 * 60_000,
  });

  // CS-8: observations for the picked signal in the active farm.
  // Disabled until the operator picks something; limit 500 is the
  // current backend cap.
  const signalObservationsQ = useQuery({
    queryKey: ["labs/map/signalObservations", farmId, signalOverlayDefId],
    queryFn: () =>
      listSignalObservations({
        farm_id: farmId,
        signal_definition_id: signalOverlayDefId ?? undefined,
        limit: 500,
      }),
    enabled: Boolean(farmId && signalOverlayDefId),
    staleTime: 30_000,
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
        blockHealth: selectedId ? (summaryQ.data?.blockHealth[selectedId] ?? null) : null,
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
      setFarmPanel("details");
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
      setFarmPanel("details");
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
      setInactivateBlockPreviewError(err instanceof Error ? err.message : "Failed to load preview");
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
      setInactivateFarmPreviewError(err instanceof Error ? err.message : "Failed to load preview");
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
  //
  // The two CS-8 useMemo hooks sit ABOVE the early returns so they
  // run on every render (rules-of-hooks). They guard internally on
  // summaryQ.data being undefined.

  const selectedSignalDefinition =
    signalDefinitionsQ.data?.find((d) => d.id === signalOverlayDefId) ?? null;
  const blockCentroids = useMemo(
    () =>
      summaryQ.data
        ? blockCentroidsFromGeojson(summaryQ.data.geojson)
        : new Map<string, [number, number]>(),
    [summaryQ.data],
  );
  const signalOverlay = useMemo(() => {
    if (!signalOverlayDefId) return { fc: null, observationCount: 0, skippedCount: 0 };
    if (!signalObservationsQ.data) {
      return {
        fc: { type: "FeatureCollection" as const, features: [] },
        observationCount: 0,
        skippedCount: 0,
      };
    }
    const built = buildSignalOverlay(signalObservationsQ.data, blockCentroids, {
      valueKind: selectedSignalDefinition?.value_kind ?? null,
    });
    return {
      fc: built.features,
      observationCount: built.features.features.length,
      skippedCount: built.skippedCount,
    };
  }, [signalOverlayDefId, signalObservationsQ.data, blockCentroids, selectedSignalDefinition]);

  // Sub-block grid overlay (PR-grid). Off by default. Product is
  // sourced from the selected block's first active imagery
  // subscription — V1 doesn't yet expose a product picker, the
  // assumption being a block typically has at most one ingest source.
  const [showGrid, setShowGrid] = useState<boolean>(false);
  const [gridIndex, setGridIndex] = useState<IndexCode>("ndvi");
  const [selectedCellId, setSelectedCellId] = useState<string | null>(null);
  const [cellClickPoint, setCellClickPoint] = useState<{ x: number; y: number } | null>(null);
  // Click pixel coords for the observation popup — anchors it next to the
  // clicked signal dot, the same way cellClickPoint anchors the cell popup.
  const [obsClickPoint, setObsClickPoint] = useState<{ x: number; y: number } | null>(null);

  // Every index the pipeline computes + stores per grid cell. Was the
  // "health trio"; expanded so the map can colour by any of them.
  const GRID_INDEX_OPTIONS: IndexCode[] = [
    "ndvi",
    "ndre",
    "ndwi",
    "evi",
    "savi",
    "gndvi",
    "ndmi",
  ];

  const subscriptionsQ = useQuery({
    queryKey: ["labs/map/subscriptions", selectedId],
    queryFn: () => listSubscriptions(selectedId!, { include_inactive: false }),
    enabled: Boolean(selectedId),
    staleTime: 60_000,
  });
  const gridProductId = subscriptionsQ.data?.[0]?.product_id ?? null;

  // Farm-wide overlay: there's no farm-level cells endpoint, so fan out
  // per gridded block (each carries its own imagery product = its first
  // active subscription) and merge client-side. Lazy — only fetched while
  // the overlay is on. One query with an internal Promise.all keeps the
  // hook count stable regardless of block count.
  const overlayBlocks = summaryQ.data?.blocks ?? [];
  const overlayBlockKey = overlayBlocks.map((b) => b.id).join(",");
  const farmGridQ = useQuery({
    queryKey: ["labs/map/farmGrid", farmId, gridIndex, overlayBlockKey],
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

  // block id -> display name, for the cell popup's "Block" row.
  const blockNameById = useMemo(() => {
    const m = new Map<string, string>();
    for (const b of summaryQ.data?.blocks ?? []) m.set(b.id, b.name ?? b.code ?? b.id);
    return m;
  }, [summaryQ.data]);

  // cellId -> { blockId, productId, lat, lon, value, time, blockName } so a
  // clicked cell can fetch its history against the right block's product
  // and the compact popup can render its current value + scene time + location.
  const cellMeta = useMemo(() => {
    const m = new Map<
      string,
      {
        blockId: string;
        productId: string;
        lat: number;
        lon: number;
        value: number | null;
        time: string | null;
        blockName: string;
      }
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

  // Block-average baseline for the selected cell. The backend anomaly
  // detector flags a cell when its mean is >= DEFAULT_K (1.5) std-devs
  // BELOW its block's own spatial mean for that scene (see
  // backend/app/modules/grid/anomaly.py). We reproduce that judgement
  // client-side from the already-loaded cells — no backend call. Returns
  // null when the block has too few valid cells (<5) or the cell value is
  // null. Per-block anomaly_z_threshold overrides are NOT surfaced in V1.
  const selectedCellBaseline = useMemo<{ blockMean: number; z: number } | null>(() => {
    if (!selectedCellId) return null;
    const meta = cellMeta.get(selectedCellId);
    if (!meta || meta.value === null) return null;
    const group = (farmGridQ.data ?? []).find((g) => g.blockId === meta.blockId);
    if (!group) return null;
    const means = group.cells
      .map((c) => (c.mean === null ? null : Number(c.mean)))
      .filter((v): v is number => v !== null);
    if (means.length < 5) return null;
    const blockMean = means.reduce((s, v) => s + v, 0) / means.length;
    const variance = means.reduce((s, v) => s + (v - blockMean) ** 2, 0) / means.length;
    const blockStd = Math.sqrt(variance);
    // Positive z = the cell sits BELOW the block average (anomaly-flagged
    // direction); >= 1.5 means the backend would flag it.
    const z = blockStd > 0 ? (blockMean - meta.value) / blockStd : 0;
    return { blockMean, z };
  }, [selectedCellId, cellMeta, farmGridQ.data]);

  const totalCellCount = useMemo(
    () => (farmGridQ.data ?? []).reduce((n, g) => n + g.cells.length, 0),
    [farmGridQ.data],
  );

  // Farm-wide worst-N (lowest mean) for the scout list + map highlight —
  // computed client-side from the merged cells (no per-block worst call).
  const farmWorstCells = useMemo<GridWorstCell[]>(
    () =>
      (farmGridQ.data ?? [])
        .flatMap((g) => g.cells)
        .filter((c) => c.mean !== null)
        .sort((a, b) => Number(a.mean) - Number(b.mean))
        .slice(0, 5)
        .map((c) => ({
          cell_id: c.cell_id,
          row_idx: c.row_idx,
          col_idx: c.col_idx,
          centroid_lon: c.centroid_lon,
          centroid_lat: c.centroid_lat,
          mean: c.mean,
          valid_pixel_pct: c.valid_pixel_pct,
          time: c.time,
          ring: null,
          sector_label: null,
        })),
    [farmGridQ.data],
  );

  // G-2: outline the worst-N cells on the heatmap so the scout list and
  // the map agree on *where* to look. Empty when hidden.
  const highlightedCellIds = useMemo<string[]>(
    () => (showGrid ? farmWorstCells.map((c) => c.cell_id) : []),
    [showGrid, farmWorstCells],
  );

  const gridCellsFc: FeatureCollection<GeoPolygon, GridCellProps> | null = useMemo(() => {
    if (!showGrid || !farmGridQ.data) return null;
    return {
      type: "FeatureCollection",
      features: farmGridQ.data.flatMap((g) =>
        g.cells.map((c) => ({
          type: "Feature" as const,
          geometry: c.geometry,
          properties: {
            cell_id: c.cell_id,
            // -1 is the no-data sentinel that MapCanvas's fill-color
            // expression maps to grey — see GridCellProps comment.
            value: c.mean === null ? -1 : Number(c.mean),
          },
        })),
      ),
    };
  }, [showGrid, farmGridQ.data]);

  // CS-8 popup: URL ?signal_obs=<id> drives a side panel that
  // hydrates from the same observations the overlay already loaded
  // — no extra round-trip. When the picker is off or the id no
  // longer matches a loaded observation (e.g. operator changed
  // signal), the panel quietly stays hidden.
  const selectedObservationId = search.get("signal_obs");
  const selectedObservation = useMemo(() => {
    if (!selectedObservationId || !signalObservationsQ.data) return null;
    return signalObservationsQ.data.find((o) => o.id === selectedObservationId) ?? null;
  }, [selectedObservationId, signalObservationsQ.data]);

  // Drop the anchor point whenever the observation popup closes via any
  // path other than the dot click that set it (deep-link cleared, back
  // nav, panel-driven removal) so a stale anchor can't reposition a
  // freshly opened popup. When `signal_obs` is absent the popup is hidden
  // and the point should be null.
  useEffect(() => {
    if (!selectedObservationId) setObsClickPoint(null);
  }, [selectedObservationId]);

  if (summaryQ.isLoading) {
    return <FullState>Loading farm map…</FullState>;
  }
  if (summaryQ.isError || !summaryQ.data) {
    return (
      <FullState>
        <p>Couldn&apos;t load map.</p>
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
  // Auto-Block is only meaningful when the farm has zero active operational
  // units — the gridder lays out a fresh grid and would otherwise collide
  // with manual work.
  const hasActiveBlocks = summary.blocks.length > 0;

  return (
    <div className="-mx-4 -my-6 flex flex-col" style={{ height: "calc(100vh - 56px)" }}>
      <Toolbar
        drawTarget={drawTarget}
        onToggleDrawBlock={() => setDrawTarget((cur) => (cur === "block" ? null : "block"))}
        onToggleDrawPivot={() => setDrawTarget((cur) => (cur === "pivot" ? null : "pivot"))}
        layerPrefs={layerPrefs}
        onLayerPrefsChange={setLayerPrefs}
        // Farm-scoped panel buttons. The "active" panel is whichever
        // sub-view is showing in the drawer right now; clicking the
        // active one closes the drawer. Sibling panels (defaults /
        // members) are hidden in edit/create modes to avoid losing
        // in-flight detail edits.
        farmDrawerMode={farmDrawerMode}
        farmPanel={farmPanel}
        onOpenPanel={(target) => {
          if (farmDrawerMode !== null && farmPanel === target) {
            // Clicking the active panel button closes the drawer.
            setFarmDrawerMode(null);
            setFarmPanel("details");
            setPendingFarmAoi(null);
            setPendingFarmAoiAreaM2(null);
            setDrawTarget(null);
            return;
          }
          // Open or switch panel.
          setFarmPanel(target);
          if (farmDrawerMode === null) setFarmDrawerMode("view");
        }}
        onCreateFarm={() => {
          setPendingFarmAoi(null);
          setPendingFarmAoiAreaM2(null);
          setFarmPanel("details");
          setFarmDrawerMode("create");
        }}
        hasActiveBlocks={hasActiveBlocks}
        onOpenAutoBlock={() => navigate(`/farms/${farmId}/blocks/auto-grid`)}
        // Farm-wide sub-block grid control (moved here from the floating
        // panel). Available whenever the farm has blocks.
        gridAvailable={summary.blocks.length > 0}
        showGrid={showGrid}
        onToggleGrid={setShowGrid}
        gridIndex={gridIndex}
        gridIndexOptions={GRID_INDEX_OPTIONS}
        onGridIndexChange={setGridIndex}
        gridCellCount={showGrid ? totalCellCount : null}
        gridWorstCells={farmWorstCells}
        gridWorstLoading={farmGridQ.isLoading}
        onSelectGridCell={(cellId) => {
          setSelectedCellId(cellId);
          closePanel();
        }}
        // Signal overlay control (moved here from the floating
        // SignalOverlayControl). Mirrors the grid control pattern.
        signalAvailable={(signalDefinitionsQ.data ?? []).length > 0}
        signalDefinitions={signalDefinitionsQ.data ?? []}
        signalDefId={signalOverlayDefId}
        onSignalChange={setSignalOverlayDefId}
        signalObsCount={signalOverlay.observationCount}
      />

      {farmDrawerMode ? (
        <FarmDrawer
          // Remount when switching between create and view of a
          // particular farm so the form state (code/name/etc) is
          // re-seeded from the right source — otherwise create-mode
          // would inherit the previously-viewed farm's values via
          // useState initializers and submit a duplicate `code`.
          key={farmDrawerMode === "create" ? "create" : `view:${summary.farm.id}`}
          mode={farmDrawerMode}
          panel={farmPanel}
          farm={farmDrawerMode === "create" ? null : summary.farm}
          inactiveBlocks={inactiveBlocks}
          draftBoundary={pendingFarmAoi}
          draftAreaM2={pendingFarmAoiAreaM2}
          drawingAoi={drawTarget === "farm_aoi"}
          submitting={createFarmMut.isPending || updateFarmMut.isPending}
          submitError={createFarmMut.error?.message ?? updateFarmMut.error?.message ?? null}
          onClose={() => {
            setFarmDrawerMode(null);
            setFarmPanel("details");
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
          onAoiUploaded={(boundary, areaM2) => {
            setPendingFarmAoi(boundary);
            setPendingFarmAoiAreaM2(areaM2);
            // Uploading replaces any in-progress draw.
            setDrawTarget(null);
          }}
        />
      ) : null}

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
            onSelect={(id) => {
              // Selecting a block (polygon or its label) closes any open
              // cell drawer so only one drawer shows at a time.
              setSelectedCellId(null);
              selectUnit(id);
            }}
            fitBoundsKey={farmId}
            drawEnabled={drawing}
            drawTarget={drawTarget ?? "block"}
            onPolygonDrawn={(poly, areaM2, target) => {
              setDrawProgress(null);
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
            onDrawProgress={setDrawProgress}
            onPivotDrawn={(r) => {
              setPendingPivot({
                lat: r.center_lat,
                lon: r.center_lon,
                radius_m: r.radius_m,
              });
            }}
            reshapeBlock={
              reshapeTarget ? { id: reshapeTarget.id, boundary: reshapeTarget.boundary } : null
            }
            onReshape={(poly) => setReshapeCandidate(poly)}
            showAoi={layerPrefs.aoi}
            showBlocks={layerPrefs.showBlocks}
            showBlockBorders={layerPrefs.borders}
            showBlockLabels={layerPrefs.labels}
            borderOpacity={layerPrefs.borderOpacity}
            blockFillOpacity={layerPrefs.blockFillOpacity}
            gridCells={gridCellsFc}
            highlightedCellIds={highlightedCellIds}
            selectedGridCellId={selectedCellId}
            onGridCellClick={(cellId, point) => {
              // Per the UX: a cell click shows ONLY the cell-info popup.
              // Close the block drawer AND the observation popup so only
              // one popup shows at a time. The click pixel coords anchor
              // the popup next to the clicked cell.
              setSelectedCellId(cellId);
              setCellClickPoint(point);
              closePanel();
              const next = new URLSearchParams(search);
              next.delete("signal_obs");
              setSearch(next, { replace: true });
            }}
            signalOverlay={signalOverlay.fc}
            onSignalClick={(observationId, point) => {
              // The URL `?signal_obs=` drives the SignalObservationPanel
              // (rendered below). Keeping the id in the URL means a
              // deep-link to a specific observation works on its own.
              // Opening an observation closes the cell popup so the two
              // don't stack. The click coords anchor the popup to the dot.
              const next = new URLSearchParams(search);
              next.set("signal_obs", observationId);
              setSearch(next, { replace: true });
              setObsClickPoint(point);
              setSelectedCellId(null);
              setCellClickPoint(null);
            }}
          />
        )}

        <MapNote drawTarget={drawTarget} />

        <DrawReadout
          progress={drawProgress}
          onCancel={() => {
            setDrawTarget(null);
            setDrawProgress(null);
          }}
        />

        {/* The grid show/index/worst control now lives in the top toolbar,
            and the per-block cell-size + backfill config now lives inside
            the block drawer (DetailPanel) — see its `gridConfig` slot
            below — since it's block-level. Nothing grid-related floats. */}

        <GridCellPopup
          open={selectedCellId !== null}
          cellId={selectedCellId}
          productId={selectedCellId ? (cellMeta.get(selectedCellId)?.productId ?? null) : null}
          indexCode={gridIndex}
          value={selectedCellId ? (cellMeta.get(selectedCellId)?.value ?? null) : null}
          lat={selectedCellId ? (cellMeta.get(selectedCellId)?.lat ?? null) : null}
          lon={selectedCellId ? (cellMeta.get(selectedCellId)?.lon ?? null) : null}
          blockName={selectedCellId ? (cellMeta.get(selectedCellId)?.blockName ?? null) : null}
          x={cellClickPoint?.x ?? null}
          y={cellClickPoint?.y ?? null}
          time={selectedCellId ? (cellMeta.get(selectedCellId)?.time ?? null) : null}
          baselineMean={selectedCellBaseline?.blockMean ?? null}
          z={selectedCellBaseline?.z ?? null}
          onClose={() => {
            setSelectedCellId(null);
            setCellClickPoint(null);
          }}
        />

        {selectedObservationId ? (
          <SignalObservationPanel
            observation={selectedObservation}
            definition={selectedSignalDefinition}
            isLoading={signalObservationsQ.isLoading}
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
            onSaveEdit={(patch) => updateBlockMut.mutate({ blockId: selectedId, patch })}
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
            // Block-level sub-block grid config (cell size + backfill).
            // Rendered as a section inside the drawer when this block has
            // an imagery subscription (= a product to grid against).
            gridConfig={
              selectedId && gridProductId ? (
                <BlockGridConfigCard blockId={selectedId} productId={gridProductId} />
              ) : null
            }
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
            onSubmit={(values) => createBlockMut.mutate({ polygon: pendingBlockPolygon, values })}
          />
        ) : null}

        {inactivateBlockOpen && selectedId ? (
          <InactivateConfirmModal
            confirmKeyword={summary.blocks.find((b) => b.id === selectedId)?.code ?? "INACTIVATE"}
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
            onSubmit={(reason) => inactivateBlockMut.mutate({ blockId: selectedId, reason })}
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
  drawTarget,
  onToggleDrawBlock,
  onToggleDrawPivot,
  layerPrefs,
  onLayerPrefsChange,
  farmDrawerMode,
  farmPanel,
  onOpenPanel,
  onCreateFarm,
  hasActiveBlocks,
  onOpenAutoBlock,
  gridAvailable,
  showGrid,
  onToggleGrid,
  gridIndex,
  gridIndexOptions,
  onGridIndexChange,
  gridCellCount,
  gridWorstCells,
  gridWorstLoading,
  onSelectGridCell,
  signalAvailable,
  signalDefinitions,
  signalDefId,
  onSignalChange,
  signalObsCount,
}: {
  drawTarget: DrawTarget | null;
  onToggleDrawBlock: () => void;
  onToggleDrawPivot: () => void;
  layerPrefs: LayerPrefs;
  onLayerPrefsChange: (next: LayerPrefs) => void;
  farmDrawerMode: FarmDrawerMode | null;
  farmPanel: FarmPanel;
  onOpenPanel: (target: FarmPanel) => void;
  onCreateFarm: () => void;
  hasActiveBlocks: boolean;
  onOpenAutoBlock: () => void;
  gridAvailable: boolean;
  showGrid: boolean;
  onToggleGrid: (next: boolean) => void;
  gridIndex: IndexCode;
  gridIndexOptions: IndexCode[];
  onGridIndexChange: (code: IndexCode) => void;
  gridCellCount: number | null;
  gridWorstCells: GridWorstCell[];
  gridWorstLoading: boolean;
  onSelectGridCell: (cellId: string) => void;
  signalAvailable: boolean;
  signalDefinitions: readonly SignalDefinition[];
  signalDefId: string | null;
  onSignalChange: (id: string | null) => void;
  signalObsCount: number;
}) {
  // The active-farm context (name, area, governorate, status) now lives
  // in the shell header next to the tenant badge — that's why this
  // toolbar no longer carries a farm switcher or farm-name label.
  //
  // Three farm-scoped panel buttons live as siblings (no nesting under
  // "Farm details"). The active button — drawer open AND current
  // panel matches — gets the filled style; clicking it closes. The
  // sibling panels (defaults / members) are hidden during edit/create
  // so the user can't accidentally lose in-flight edits.
  const drawerOpen = farmDrawerMode !== null;
  const showSiblings = farmDrawerMode === null || farmDrawerMode === "view";

  function panelClass(target: FarmPanel) {
    const active = drawerOpen && farmPanel === target;
    return `rounded px-2 py-0.5 text-[11px] font-medium ${
      active
        ? "bg-slate-900 text-white"
        : "border border-slate-300 text-slate-700 hover:bg-slate-50"
    }`;
  }

  return (
    <header className="flex h-10 items-center justify-between gap-3 border-b border-slate-200 bg-white px-3">
      <div className="flex items-center gap-2 text-[12px] text-slate-700">
        <div className="flex items-center gap-1 border-r border-slate-200 pe-2">
          <button
            type="button"
            onClick={() => onOpenPanel("details")}
            aria-pressed={drawerOpen && farmPanel === "details"}
            className={panelClass("details")}
          >
            Farm details
          </button>
          {showSiblings ? (
            <>
              <button
                type="button"
                onClick={() => onOpenPanel("defaults")}
                aria-pressed={drawerOpen && farmPanel === "defaults"}
                className={panelClass("defaults")}
              >
                Block defaults
              </button>
              <button
                type="button"
                onClick={() => onOpenPanel("members")}
                aria-pressed={drawerOpen && farmPanel === "members"}
                className={panelClass("members")}
              >
                Members
              </button>
            </>
          ) : null}
        </div>
        <button
          type="button"
          onClick={onCreateFarm}
          className="rounded border border-slate-300 px-2 py-0.5 text-[11px] text-slate-700 hover:bg-slate-50"
        >
          + New farm
        </button>
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-slate-500">
        <LayerToggle
          label="AOI"
          checked={layerPrefs.aoi}
          onChange={(v) => onLayerPrefsChange({ ...layerPrefs, aoi: v })}
        />
        <LayerToggle
          label="Blocks"
          checked={layerPrefs.showBlocks}
          onChange={(v) => onLayerPrefsChange({ ...layerPrefs, showBlocks: v })}
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
          <span className="text-[10px] text-slate-500">Borders</span>
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
        <label className="flex items-center gap-1" title="Block fill transparency">
          <span className="text-[10px] text-slate-500">Fill</span>
          <input
            type="range"
            min={0}
            max={100}
            step={5}
            value={Math.round(layerPrefs.blockFillOpacity * 100)}
            onChange={(e) =>
              onLayerPrefsChange({
                ...layerPrefs,
                blockFillOpacity: Number(e.target.value) / 100,
              })
            }
            className="h-1 w-20 cursor-pointer"
            aria-label="Block fill opacity"
          />
        </label>
        <GridToolbarControl
          available={gridAvailable}
          showGrid={showGrid}
          onToggleGrid={onToggleGrid}
          indexCode={gridIndex}
          indexOptions={gridIndexOptions}
          onIndexChange={onGridIndexChange}
          cellCount={gridCellCount}
          worstCells={gridWorstCells}
          worstLoading={gridWorstLoading}
          onSelectCell={onSelectGridCell}
        />
        <SignalToolbarControl
          available={signalAvailable}
          definitions={signalDefinitions}
          selectedDefinitionId={signalDefId}
          onChange={onSignalChange}
          obsCount={signalObsCount}
        />
        <span className="text-slate-300">|</span>
        <Swatch color="#97C459" label="Healthy" />
        <Swatch color="#EF9F27" label="Watch" />
        <Swatch color="#E24B4A" label="Critical" />
        <button
          type="button"
          onClick={onOpenAutoBlock}
          disabled={hasActiveBlocks}
          title={
            hasActiveBlocks
              ? "Auto-Block lays out a fresh grid — disabled while active blocks exist."
              : "Generate a grid of blocks across the farm AOI"
          }
          className="ms-2 rounded border border-slate-300 px-2 py-0.5 text-[11px] text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Auto-Block
        </button>
        <button
          type="button"
          onClick={onToggleDrawBlock}
          className={`rounded px-2 py-0.5 text-[11px] font-medium ${
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

// Farm-wide sub-block grid control, in the top toolbar (replaces the
// old floating GridOverlayPanel). Toggle + index live inline like the
// other layer controls; the worst-cells list is a small popover so the
// toolbar stays one row. Renders nothing until the farm has blocks.
function GridToolbarControl({
  available,
  showGrid,
  onToggleGrid,
  indexCode,
  indexOptions,
  onIndexChange,
  cellCount,
  worstCells,
  worstLoading,
  onSelectCell,
}: {
  available: boolean;
  showGrid: boolean;
  onToggleGrid: (next: boolean) => void;
  indexCode: IndexCode;
  indexOptions: IndexCode[];
  onIndexChange: (code: IndexCode) => void;
  cellCount: number | null;
  worstCells: GridWorstCell[];
  worstLoading: boolean;
  onSelectCell: (cellId: string) => void;
}) {
  const [worstOpen, setWorstOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!worstOpen) return;
    const handler = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setWorstOpen(false);
    };
    window.addEventListener("mousedown", handler);
    return () => window.removeEventListener("mousedown", handler);
  }, [worstOpen]);

  if (!available) return null;

  return (
    <>
      <span className="text-slate-300">|</span>
      <LayerToggle label="Grid" checked={showGrid} onChange={onToggleGrid} />
      {showGrid ? (
        <>
          {cellCount != null ? (
            <span className="text-[10px] text-slate-400">{cellCount} cells</span>
          ) : null}
          <select
            value={indexCode}
            onChange={(e) => onIndexChange(e.target.value as IndexCode)}
            aria-label="Grid index"
            className="rounded border border-slate-300 bg-white px-1 py-0.5 text-[11px] text-slate-700"
          >
            {indexOptions.map((c) => (
              <option key={c} value={c}>
                {c.toUpperCase()}
              </option>
            ))}
          </select>
          <div ref={wrapRef} className="relative">
            <button
              type="button"
              onClick={() => setWorstOpen((o) => !o)}
              aria-expanded={worstOpen}
              className="rounded border border-slate-300 px-1.5 py-0.5 text-[11px] text-slate-700 hover:bg-slate-50"
            >
              Lowest ▾
            </button>
            {worstOpen ? (
              <div className="absolute end-0 top-full z-30 mt-1 w-48 rounded-md border border-slate-200 bg-white p-2 text-[11px] shadow-lg">
                <p className="mb-1 font-medium text-slate-600">
                  Lowest {indexCode.toUpperCase()} cells
                </p>
                {worstLoading ? (
                  <p className="text-slate-400">Loading…</p>
                ) : worstCells.length === 0 ? (
                  <p className="text-slate-400">No observations yet.</p>
                ) : (
                  <ul className="flex flex-col gap-0.5">
                    {worstCells.map((c, i) => (
                      <li key={c.cell_id}>
                        <button
                          type="button"
                          onClick={() => {
                            onSelectCell(c.cell_id);
                            setWorstOpen(false);
                          }}
                          className="flex w-full items-center justify-between rounded px-1 py-0.5 hover:bg-slate-50"
                        >
                          <span className="text-slate-500">#{i + 1}</span>
                          <span className="font-mono text-slate-800">
                            {c.mean === null ? "—" : Number(c.mean).toFixed(3)}
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ) : null}
          </div>
        </>
      ) : null}
    </>
  );
}

// Signal overlay control, in the top toolbar (replaces the old floating
// SignalOverlayControl). Mirrors GridToolbarControl: a label + inline
// select, with the observation count as muted text once a signal is
// picked. Renders nothing until the tenant has signal definitions.
function SignalToolbarControl({
  available,
  definitions,
  selectedDefinitionId,
  onChange,
  obsCount,
}: {
  available: boolean;
  definitions: readonly SignalDefinition[];
  selectedDefinitionId: string | null;
  onChange: (id: string | null) => void;
  obsCount: number;
}) {
  if (!available) return null;
  return (
    <>
      <span className="text-slate-300">|</span>
      <label className="flex items-center gap-1">
        <span className="text-[10px] text-slate-500">Signal</span>
        <select
          value={selectedDefinitionId ?? ""}
          onChange={(e) => onChange(e.target.value === "" ? null : e.target.value)}
          aria-label="Signal overlay"
          className="rounded border border-slate-300 bg-white px-1 py-0.5 text-[11px] text-slate-700"
        >
          <option value="">— none —</option>
          {definitions.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name} ({d.code})
            </option>
          ))}
        </select>
      </label>
      {selectedDefinitionId ? (
        <span className="text-[10px] text-slate-400">{obsCount} obs</span>
      ) : null}
    </>
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
      <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: color }} />
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
          <strong>Drawing block</strong> · click to add vertices · <strong>double-click</strong> to
          finish
        </div>
      ) : drawTarget === "farm_aoi" ? (
        <div>
          <strong>Drawing farm AOI</strong> · click to add vertices · <strong>double-click</strong>{" "}
          to finish
        </div>
      ) : drawTarget === "pivot" ? (
        <div>
          <strong>Drawing pivot</strong> · click center · move to set radius · click to confirm ·{" "}
          <strong>Esc</strong> cancels
        </div>
      ) : (
        <div>
          <strong>Click</strong> any solid unit · <strong>click</strong> an index to expand chart
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

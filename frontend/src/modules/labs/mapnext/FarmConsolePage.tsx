// Farm Console — redesigned Farm Management surface (/labs/map-next).
//
// A progressive-disclosure re-take of /labs/map: slim view bar + units
// rail + a two-tier inspector (monitor by default, manage one click away),
// with farm-level config behind a settings drawer. Built as a NEW page so
// it can be iterated and A/B'd before replacing /labs/map. Reuses the
// existing data loaders (loadMapSummary / loadUnitDetail) and MapCanvas.
// See docs/proposals/farm-management-redesign.md.
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import type { FeatureCollection, Polygon } from "geojson";

import {
  getFarm,
  getFarmInactivationPreview,
  inactivateFarm,
  listFarms,
  reactivateFarm,
  updateFarm,
  type FarmUpdatePayload,
  type WaterSource,
} from "@/api/farms";
import {
  autoGrid,
  createBlock,
  createPivot,
  getBlock,
  getBlockInactivationPreview,
  inactivateBlock,
  updateBlock,
  type AutoGridCandidate,
  type Block,
  type BlockDetail,
} from "@/api/blocks";
import { getFarmGridCells, getGridCells } from "@/api/grid";
import { mapWithConcurrency } from "@/modules/labs/map/api";
import { griddedBlocks } from "./gridOverlay";
import { listSubscriptions } from "@/api/imagery";
import type { IndexCode as ApiIndexCode } from "@/api/indices";
import { listSignalDefinitions, listSignalObservations } from "@/api/signals";
import { loadBlockHealth, loadMapSummary, loadUnitDetail, toUnitIntegration } from "../map/api";
import { MapCanvas, type GridCellProps, type DrawProgress } from "../map/MapCanvas";
import { GridCellPopup, type CellItem } from "@/modules/grid/GridCellPopup";
import { useRecommendations } from "@/queries/recommendations";
import { useAlerts } from "@/queries/alerts";
import { InactivateConfirmModal } from "../map/InactivateConfirmModal";
import { SignalObservationPanel } from "../map/SignalObservationPanel";
import { buildSignalOverlay, blockCentroidsFromGeojson } from "../map/signalOverlay";
import { FarmMembersTab } from "../map/FarmMembersTab";
import { BlockDefaultsPanel } from "./BlockDefaultsPanel";
import { usePrefs } from "@/prefs/PrefsContext";
import { useCapability } from "@/rbac/useCapability";
import { LAST_FARM_KEY } from "./constants";
import { AutoBlockPanel, CreateBlockPanel, CreatePivotPanel, DrawHintBar } from "./createFlows";
import { CreateFarmFlow } from "./CreateFarmFlow";
import { BulkAoiUploadPanel } from "./BulkAoiUploadPanel";
import type { BulkPreviewProps } from "../map/MapCanvas";
import type { ExistingBlock } from "@/lib/aoi/bulk";
import { BlockDock } from "./BlockDock";
import { UnitsRail } from "./UnitsRail";
import { ViewBar, type LayerState } from "./ViewBar";
import { Page } from "@/components/Page";

export function FarmConsolePage(): ReactNode {
  const { farmId } = useParams<{ farmId?: string }>();
  const [search] = useSearchParams();
  // Creating a farm is a tenant-level flow, not a farm-scoped one: a brand-new
  // tenant has no farm to scope to, so it branches ahead of the console.
  if (search.get("create") === "farm") return <CreateFarmFlow contextFarmId={farmId} />;
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
  const { t, i18n } = useTranslation("farmConsole");
  const [search, setSearch] = useSearchParams();
  const selectedId = search.get("unit");

  const qc = useQueryClient();
  const canCreateFarm = useCapability("farm.create");
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
  // Grid overlay. Defaults ON for a farm that has any sub-block grid
  // configured — someone who went to the trouble of zoning a block wants to
  // see the zones without hunting through the Layers popover. Latched after
  // the first summary so a later toggle-off is not undone by a refetch, and
  // per farm so switching farms re-evaluates.
  const [showGrid, setShowGrid] = useState(false);
  const gridDefaultedFor = useRef<string | null>(null);
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
  // Farm-level inactivate/reactivate (rare, manager-only): triggered from the
  // settings drawer's danger zone, confirmed by a page-level modal.
  const [inactivateFarmOpen, setInactivateFarmOpen] = useState(false);
  const canInactivateFarm = useCapability("farm.delete", { farmId });
  const [resetKey, setResetKey] = useState(0);

  // Native +Add create flows (draw on the console map; no navigation).
  const [drawTarget, setDrawTarget] = useState<"block" | "pivot" | null>(null);
  const [drawProgress, setDrawProgress] = useState<DrawProgress | null>(null);
  const [pendingBlock, setPendingBlock] = useState<{ polygon: Polygon; areaM2: number } | null>(
    null,
  );
  const [pendingPivot, setPendingPivot] = useState<{
    lat: number;
    lon: number;
    radiusM: number;
  } | null>(null);
  // Auto-block panel. The per-block area cap is held canonically in m²; the
  // panel renders it in the user's preferred area unit. autoCellSizeM is the
  // grid cell the backend derived on the last compute (for display only).
  const { unit: areaUnit } = usePrefs();
  const [autoOpen, setAutoOpen] = useState(false);
  const [maxAreaM2, setMaxAreaM2] = useState(40_000); // ≈ a 200 m cell
  const [autoCellSizeM, setAutoCellSizeM] = useState<number | null>(null);
  const [candidates, setCandidates] = useState<AutoGridCandidate[] | null>(null);
  const [selectedCandidates, setSelectedCandidates] = useState<Set<string>>(new Set());
  const [autoComputing, setAutoComputing] = useState(false);
  const [autoCreating, setAutoCreating] = useState(false);
  const [autoCreatedCount, setAutoCreatedCount] = useState<number | null>(null);
  const [autoError, setAutoError] = useState<string | null>(null);
  // Bulk AOI upload panel (+Add → Upload AOI files…).
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkPreviewFc, setBulkPreviewFc] = useState<FeatureCollection<
    Polygon,
    BulkPreviewProps
  > | null>(null);
  const canBulkReplace = useCapability("block.delete", { farmId });

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
    // Language is part of the key: loadUnitDetail bakes localized alert text
    // into the detail, so switching locale must refetch to re-localize.
    queryKey: ["labs/mapnext/detail", farmId, selectedId, i18n.language],
    queryFn: () =>
      loadUnitDetail({
        farmId,
        blockId: selectedId as string,
        blocksById,
        activePlan: summaryQ.data?.activePlan,
      }),
    enabled: Boolean(selectedId && blocksById.size > 0),
    staleTime: 30_000,
  });

  // Integration health rides its own query so it can never hold up the map
  // (it used to sit inside loadMapSummary's Promise.all and gate the whole
  // page). It only feeds two rows in the dock, which fill in on arrival.
  const blockHealthQ = useQuery({
    queryKey: ["labs/mapnext/blockHealth", farmId],
    queryFn: () => loadBlockHealth(farmId),
    staleTime: 60_000,
  });
  const selectedIntegration = toUnitIntegration(
    selectedId ? (blockHealthQ.data?.[selectedId] ?? null) : null,
  );

  // First active imagery product for the selected block — needed for grid config.
  const subsQ = useQuery({
    queryKey: ["labs/mapnext/subs", selectedId],
    queryFn: () => listSubscriptions(selectedId as string, { include_inactive: false }),
    enabled: Boolean(selectedId),
    staleTime: 60_000,
  });
  const gridProductId = subsQ.data?.[0]?.product_id ?? null;

  // Which blocks carry a grid — read off the summary, which is also what
  // decides whether the overlay comes up at all.
  const gridded = useMemo(
    () => griddedBlocks(summaryQ.data?.blocks, summaryQ.data?.summaries),
    [summaryQ.data],
  );
  const overlayKey = gridded.map((g) => g.blockId).join(",");

  useEffect(() => {
    if (!summaryQ.data || gridDefaultedFor.current === farmId) return;
    gridDefaultedFor.current = farmId;
    setShowGrid(gridded.length > 0);
  }, [summaryQ.data, farmId, gridded.length]);

  // Farm-wide grid in ONE request. This used to fan out per gridded block
  // and merge client-side — 36 concurrent requests on a 36-block farm,
  // each re-paying auth, a connection out of the api's 15-slot pool and
  // two hypertable queries, all serialised through a single-worker pod.
  // That is what made the overlay take seconds to appear, and it is the
  // same N+1 shape that exhausted the pool once before (#311).
  //
  // The per-block path stays as a fallback: charts deploy independently,
  // so a new frontend can meet an api that has no farm route yet. It is
  // bounded to 4 in flight for exactly the reason above — degrade, don't
  // take the pool down.
  const farmGridQ = useQuery({
    queryKey: ["labs/mapnext/farmGrid", farmId, activeIndex, overlayKey],
    queryFn: async () => {
      const farmWide = await getFarmGridCells(farmId, activeIndex);
      if (farmWide) {
        return farmWide.blocks.map((b) => ({
          blockId: b.block_id,
          productId: b.product_id,
          cells: b.cells,
        }));
      }
      return mapWithConcurrency(gridded, 4, async ({ blockId, productId }) => {
        const res = await getGridCells(blockId, productId, activeIndex);
        return { blockId, productId, cells: res.cells };
      });
    },
    enabled: Boolean(showGrid && gridded.length > 0),
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
    const vals = (group?.cells ?? [])
      .map((c) => (c.mean === null ? null : Number(c.mean)))
      .filter((v): v is number => v != null);
    if (vals.length < 2) return null;
    const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
    const variance = vals.reduce((a, b) => a + (b - mean) ** 2, 0) / vals.length;
    const std = Math.sqrt(variance);
    return { blockMean: mean, z: std > 0 ? (mean - meta.value) / std : 0 };
  }, [selectedCellId, cellMeta, farmGridQ.data]);

  // Cell-scoped outputs (per-cell P2): open recs + alerts for the farm, grouped
  // by the cell they were attributed to, so the grid popup can surface "what's
  // happening in this zone".
  const isAr = i18n.language === "ar";
  const cellRecsQ = useRecommendations({ farm_id: farmId, state: "open", limit: 500 });
  const cellAlertsQ = useAlerts({ farm_id: farmId, status: "open", limit: 500 });
  const cellItemsByCell = useMemo(() => {
    const map = new Map<string, CellItem[]>();
    for (const r of cellRecsQ.data ?? []) {
      if (!r.cell_id) continue;
      const text = (isAr && r.text_ar) || r.text_en;
      map.set(r.cell_id, [
        ...(map.get(r.cell_id) ?? []),
        { id: r.id, kind: "rec", severity: r.severity, text },
      ]);
    }
    for (const a of cellAlertsQ.data ?? []) {
      if (!a.cell_id) continue;
      const text = ((isAr && a.diagnosis_ar) || a.diagnosis_en) ?? a.rule_code;
      map.set(a.cell_id, [
        ...(map.get(a.cell_id) ?? []),
        { id: a.id, kind: "alert", severity: a.severity, text },
      ]);
    }
    return map;
  }, [cellRecsQ.data, cellAlertsQ.data, isAr]);

  // Signal overlay: definitions for the picker + observations for the active one.
  const signalDefsQ = useQuery({
    queryKey: ["labs/mapnext/signalDefs"],
    queryFn: () => listSignalDefinitions(),
    staleTime: 5 * 60_000,
  });
  const signalObsQ = useQuery({
    queryKey: ["labs/mapnext/signalObs", farmId, signalDefId],
    queryFn: () =>
      listSignalObservations({
        farm_id: farmId,
        signal_definition_id: signalDefId ?? undefined,
        limit: 500,
      }),
    enabled: Boolean(farmId && signalDefId),
    staleTime: 30_000,
  });
  const selectedSignalDef = signalDefsQ.data?.find((d) => d.id === signalDefId) ?? null;
  const blockCentroids = useMemo(
    () =>
      summaryQ.data
        ? blockCentroidsFromGeojson(summaryQ.data.geojson)
        : new Map<string, [number, number]>(),
    [summaryQ.data],
  );
  const signalOverlayFc = useMemo(() => {
    if (!signalDefId) return null;
    if (!signalObsQ.data) return { type: "FeatureCollection" as const, features: [] };
    return buildSignalOverlay(signalObsQ.data, blockCentroids, {
      valueKind: selectedSignalDef?.value_kind ?? null,
    }).features;
  }, [signalDefId, signalObsQ.data, blockCentroids, selectedSignalDef]);
  const selectedObs = useMemo(
    () =>
      selectedObsId && signalObsQ.data
        ? (signalObsQ.data.find((o) => o.id === selectedObsId) ?? null)
        : null,
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
    mutationFn: ({ blockId, boundary }: { blockId: string; boundary: Polygon }) =>
      updateBlock(blockId, { boundary }),
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
    mutationFn: ({ blockId, reason }: { blockId: string; reason: string }) =>
      inactivateBlock(blockId, { reason }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["labs/mapnext/summary"] });
      setInactivateOpen(false);
      deselect();
    },
  });

  // Farm-level inactivate (cascades to every active block) + reactivate.
  const invalidateFarm = () => {
    void qc.invalidateQueries({ queryKey: ["labs/mapnext/summary"] });
    void qc.invalidateQueries({ queryKey: ["labs/mapnext/farm", farmId] });
    void qc.invalidateQueries({ queryKey: ["labs/mapnext/farmsList"] });
  };
  const farmInactivatePreviewQ = useQuery({
    queryKey: ["labs/mapnext/farmInactivatePreview", farmId],
    queryFn: () => getFarmInactivationPreview(farmId),
    enabled: inactivateFarmOpen,
  });
  const inactivateFarmMut = useMutation({
    mutationFn: (reason: string) => inactivateFarm(farmId, { reason }),
    onSuccess: () => {
      invalidateFarm();
      setInactivateFarmOpen(false);
      deselect();
      flash(t("dangerZone.inactivated"));
    },
  });
  const reactivateFarmMut = useMutation({
    mutationFn: () => reactivateFarm(farmId, { restore_blocks: true }),
    onSuccess: () => {
      invalidateFarm();
      flash(t("dangerZone.reactivated"));
    },
  });

  // ---- Native create flows ------------------------------------------------
  const resetCreate = () => {
    setDrawTarget(null);
    setDrawProgress(null);
    setPendingBlock(null);
    setPendingPivot(null);
  };
  const closeAuto = () => {
    setAutoOpen(false);
    setCandidates(null);
    setSelectedCandidates(new Set());
    setAutoError(null);
    setAutoCreatedCount(null);
    setAutoCellSizeM(null);
  };
  const closeBulk = () => {
    setBulkOpen(false);
    setBulkPreviewFc(null);
  };
  const startDrawBlock = () => {
    closeAuto();
    closeBulk();
    setReshapeTarget(null);
    setPendingPivot(null);
    setPendingBlock(null);
    setDrawTarget("block");
  };
  const startDrawPivot = () => {
    closeAuto();
    closeBulk();
    setReshapeTarget(null);
    setPendingBlock(null);
    setPendingPivot(null);
    setDrawTarget("pivot");
  };
  const startAutoBlock = () => {
    resetCreate();
    setReshapeTarget(null);
    closeBulk();
    setAutoOpen(true);
  };
  const startBulkUpload = () => {
    resetCreate();
    setReshapeTarget(null);
    closeAuto();
    setBulkOpen(true);
  };
  // Farm creation lives in its own (non farm-scoped) view — flip the flag in
  // the URL so it survives a reload and the browser Back button leaves it.
  const startCreateFarm = () => {
    const next = new URLSearchParams(search);
    next.set("create", "farm");
    next.delete("unit");
    setSearch(next);
  };

  // Existing blocks (code + boundary) for the bulk-upload client classifier.
  const existingBlocks = useMemo<ExistingBlock[]>(() => {
    const out: ExistingBlock[] = [];
    for (const f of summaryQ.data?.geojson.features ?? []) {
      const code = blocksById.get(f.properties.id)?.code;
      if (code) out.push({ code, geometry: f.geometry });
    }
    return out;
  }, [summaryQ.data, blocksById]);

  const createBlockMut = useMutation({
    mutationFn: ({ polygon, code, name }: { polygon: Polygon; code: string; name: string }) =>
      createBlock(farmId, { code, name: name || null, boundary: polygon, unit_type: "block" }),
    onSuccess: (newBlock) => {
      void qc.invalidateQueries({ queryKey: ["labs/mapnext/summary"] });
      resetCreate();
      select(newBlock.id);
      flash(t("create.blockCreated"));
    },
  });
  const createPivotMut = useMutation({
    mutationFn: ({
      lat,
      lon,
      radiusM,
      code,
      name,
      sectorCount,
    }: {
      lat: number;
      lon: number;
      radiusM: number;
      code: string;
      name: string;
      sectorCount: number;
    }) =>
      createPivot(farmId, {
        code,
        name: name || null,
        center: { lat, lon },
        radius_m: radiusM,
        sector_count: sectorCount,
      }),
    onSuccess: (result) => {
      void qc.invalidateQueries({ queryKey: ["labs/mapnext/summary"] });
      resetCreate();
      select(result.pivot.id);
      flash(t("create.pivotCreated"));
    },
  });

  const computeAutoGrid = async () => {
    setAutoComputing(true);
    setAutoError(null);
    setAutoCreatedCount(null);
    try {
      const res = await autoGrid(farmId, { maxAreaM2 });
      setAutoCellSizeM(res.cell_size_m);
      setCandidates(res.candidates);
      setSelectedCandidates(new Set(res.candidates.map((c) => c.code)));
    } catch (err) {
      setAutoError(err instanceof Error ? err.message : String(err));
    } finally {
      setAutoComputing(false);
    }
  };
  const commitAutoBlock = async () => {
    if (!candidates) return;
    const chosen = candidates.filter((c) => selectedCandidates.has(c.code));
    setAutoCreating(true);
    setAutoError(null);
    setAutoCreatedCount(0);
    try {
      let done = 0;
      for (const c of chosen) {
        await createBlock(farmId, {
          code: c.code,
          name: c.code,
          boundary: c.boundary,
          unit_type: "block",
        });
        done += 1;
        setAutoCreatedCount(done);
      }
      void qc.invalidateQueries({ queryKey: ["labs/mapnext/summary"] });
      closeAuto();
      flash(t("autoBlock.created", { n: chosen.length }));
    } catch (err) {
      setAutoError(err instanceof Error ? err.message : String(err));
    } finally {
      setAutoCreating(false);
    }
  };

  // Preview overlay: the candidates currently selected for creation.
  const autoBlockPreviewFc = useMemo<FeatureCollection<Polygon> | null>(() => {
    if (!autoOpen || !candidates) return null;
    return {
      type: "FeatureCollection",
      features: candidates
        .filter((c) => selectedCandidates.has(c.code))
        .map((c) => ({
          type: "Feature" as const,
          geometry: c.boundary,
          properties: { code: c.code },
        })),
    };
  }, [autoOpen, candidates, selectedCandidates]);

  if (summaryQ.isLoading) {
    return (
      <div className="grid h-full place-items-center text-sm text-ap-muted">
        {t("page.loading")}
      </div>
    );
  }
  if (summaryQ.isError || !summaryQ.data) {
    return (
      <div className="grid h-full place-items-center gap-3 text-center text-sm text-ap-muted">
        <p>{t("page.loadError")}</p>
        <button
          type="button"
          onClick={() => summaryQ.refetch()}
          className="rounded-md bg-ap-primary px-3 py-1.5 text-white"
        >
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
    <Page width="bleed">
      <ViewBar
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
        onAddBlock={startDrawBlock}
        onAddPivot={startDrawPivot}
        onAutoBlock={startAutoBlock}
        onBulkUpload={startBulkUpload}
        onAddFarm={canCreateFarm ? startCreateFarm : undefined}
      />

      <div className="flex min-h-0 flex-1">
        <UnitsRail
          blocks={summary.blocks}
          summaries={summary.summaries}
          selectedId={selectedId}
          onSelect={select}
        />

        {/* Map + dock share one column so the dock spans the map canvas only,
            and follows the rail as it collapses/expands. */}
        <div className="flex min-w-0 flex-1 flex-col">
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
            reshapeBlock={
              reshapeTarget ? { id: reshapeTarget.id, boundary: reshapeTarget.boundary } : null
            }
            onReshape={(poly) => setReshapeCandidate(poly)}
            drawEnabled={drawTarget != null && !reshaping}
            drawTarget={drawTarget ?? "block"}
            onDrawProgress={setDrawProgress}
            onPolygonDrawn={(poly, areaM2, target) => {
              setDrawProgress(null);
              if (target === "block") setPendingBlock({ polygon: poly, areaM2 });
            }}
            onPivotDrawn={(r) =>
              setPendingPivot({ lat: r.center_lat, lon: r.center_lon, radiusM: r.radius_m })
            }
            autoBlockPreview={autoBlockPreviewFc}
            bulkPreview={bulkPreviewFc}
          />

          {/* Draw-in-progress hint (before a shape is completed) */}
          {drawTarget && !pendingBlock && !pendingPivot ? (
            <DrawHintBar
              kind={drawTarget}
              vertices={drawProgress?.vertices}
              areaM2={drawProgress?.areaM2}
              onCancel={resetCreate}
            />
          ) : null}

          {/* Create-block capture (after drawing a polygon) */}
          {pendingBlock ? (
            <CreateBlockPanel
              areaM2={pendingBlock.areaM2}
              submitting={createBlockMut.isPending}
              error={createBlockMut.isError ? t("create.createFailed") : null}
              onSubmit={({ code, name }) =>
                createBlockMut.mutate({ polygon: pendingBlock.polygon, code, name })
              }
              onCancel={resetCreate}
            />
          ) : null}

          {/* Create-pivot capture (after drawing a center + radius) */}
          {pendingPivot ? (
            <CreatePivotPanel
              centerLat={pendingPivot.lat}
              centerLon={pendingPivot.lon}
              radiusM={pendingPivot.radiusM}
              submitting={createPivotMut.isPending}
              error={createPivotMut.isError ? t("create.createFailed") : null}
              onSubmit={({ code, name, sector_count }) =>
                createPivotMut.mutate({
                  lat: pendingPivot.lat,
                  lon: pendingPivot.lon,
                  radiusM: pendingPivot.radiusM,
                  code,
                  name,
                  sectorCount: sector_count,
                })
              }
              onCancel={resetCreate}
            />
          ) : null}

          {/* Auto-block panel (max area → compute → pick → create) */}
          {autoOpen ? (
            <AutoBlockPanel
              maxAreaM2={maxAreaM2}
              onMaxAreaM2={setMaxAreaM2}
              unit={areaUnit}
              effectiveCellSizeM={autoCellSizeM}
              onCompute={() => void computeAutoGrid()}
              computing={autoComputing}
              candidates={candidates}
              selected={selectedCandidates}
              onToggle={(code) =>
                setSelectedCandidates((prev) => {
                  const next = new Set(prev);
                  if (next.has(code)) next.delete(code);
                  else next.add(code);
                  return next;
                })
              }
              onToggleAll={(all) =>
                setSelectedCandidates(
                  all ? new Set((candidates ?? []).map((c) => c.code)) : new Set(),
                )
              }
              creating={autoCreating}
              progressDone={autoCreatedCount}
              error={autoError}
              onCreate={() => void commitAutoBlock()}
              onClose={closeAuto}
            />
          ) : null}

          {/* Bulk AOI upload panel (drop many files → review → reconcile) */}
          {bulkOpen ? (
            <BulkAoiUploadPanel
              farmId={farmId}
              existing={existingBlocks}
              canReplace={canBulkReplace}
              onPreviewChange={setBulkPreviewFc}
              onCommitted={({ created, replaced, reused, errors }) => {
                void qc.invalidateQueries({ queryKey: ["labs/mapnext/summary"] });
                flash(t("bulk.committed", { created, replaced, reused, errors }));
              }}
              onClose={closeBulk}
            />
          ) : null}

          {/* Reshape banner */}
          {reshaping ? (
            <div className="absolute left-1/2 top-3.5 z-20 flex -translate-x-1/2 items-center gap-3 rounded-xl bg-ap-panel px-4 py-2 shadow-card">
              <span className="text-sm font-semibold text-ap-ink">{t("page.reshapeTitle")}</span>
              <button
                type="button"
                disabled={!reshapeCandidate || reshapeMut.isPending}
                onClick={() =>
                  reshapeCandidate &&
                  reshapeMut.mutate({ blockId: reshapeTarget.id, boundary: reshapeCandidate })
                }
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
              cellItems={cellItemsByCell.get(selectedCellId) ?? []}
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

          {/* Inactive-farm banner — the way back from a farm inactivation. */}
          {!summary.farm.is_active ? (
            <div className="absolute bottom-4 end-4 z-20 flex items-center gap-2 rounded-xl bg-amber-50 px-3.5 py-2 text-xs text-amber-900 shadow-card">
              <span>{t("dangerZone.inactiveSince", { date: summary.farm.active_to ?? "—" })}</span>
              {canInactivateFarm ? (
                <button
                  type="button"
                  onClick={() => reactivateFarmMut.mutate()}
                  disabled={reactivateFarmMut.isPending}
                  className="rounded-lg bg-amber-700 px-2.5 py-1 text-[11px] font-semibold text-white disabled:opacity-50"
                >
                  {reactivateFarmMut.isPending
                    ? t("dangerZone.reactivating")
                    : t("dangerZone.reactivate")}
                </button>
              ) : null}
            </div>
          ) : null}
        </main>

          {/* Block detail spans the map canvas, not the whole page — see
              docs/proposals/block-dock.html. */}
          {selectedId ? (
            <BlockDock
              detail={detailQ.data}
              integration={selectedIntegration}
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
            setInactivateFarmOpen(true);
          }}
          onReactivateFarm={() => reactivateFarmMut.mutate()}
          reactivating={reactivateFarmMut.isPending}
          reactivateError={reactivateFarmMut.isError ? t("dangerZone.reactivateError") : null}
          onClose={() => setSettingsOpen(false)}
        />
      ) : null}

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

      {inactivateFarmOpen ? (
        <InactivateConfirmModal
          confirmKeyword={summary.farm.code}
          entityLabel="farm"
          preview={farmInactivatePreviewQ.data ?? null}
          previewError={farmInactivatePreviewQ.isError ? t("page.previewError") : null}
          submitting={inactivateFarmMut.isPending}
          submitError={inactivateFarmMut.isError ? t("manage.saveError") : null}
          onCancel={() => setInactivateFarmOpen(false)}
          onSubmit={(reason) => inactivateFarmMut.mutate(reason)}
        />
      ) : null}
    </Page>
  );
}

// Farm-level config (rare, manager-only). Native panels: block defaults +
// members reuse the existing tab components; the Farm tab is a compact form.
// One quiet entry point off the daily surface.
type SettingsTab = "defaults" | "members" | "farm";

interface SettingsDrawerProps {
  farmId: string;
  farmName: string;
  canInactivate: boolean;
  onInactivateFarm: () => void;
  onReactivateFarm: () => void;
  reactivating: boolean;
  reactivateError: string | null;
  onClose: () => void;
}

function SettingsDrawer({
  farmId,
  farmName,
  canInactivate,
  onInactivateFarm,
  onReactivateFarm,
  reactivating,
  reactivateError,
  onClose,
}: SettingsDrawerProps): ReactNode {
  const { t } = useTranslation("farmConsole");
  const [tab, setTab] = useState<SettingsTab>("farm");
  const tabs: { id: SettingsTab; label: string }[] = [
    { id: "farm", label: t("settings.tabFarm") },
    { id: "defaults", label: t("settings.tabDefaults") },
    { id: "members", label: t("settings.tabMembers") },
  ];
  return (
    <>
      <button
        type="button"
        aria-label="Close settings"
        className="fixed inset-0 z-[90] bg-ap-ink/30"
        onClick={onClose}
      />
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
                (tab === tb.id
                  ? "border-ap-primary text-ap-primary"
                  : "border-transparent text-ap-muted hover:text-ap-ink")
              }
            >
              {tb.label}
            </button>
          ))}
        </div>
        <div className="flex-1 overflow-auto p-5">
          {tab === "farm" ? (
            <FarmEditTab
              farmId={farmId}
              canInactivate={canInactivate}
              onInactivateFarm={onInactivateFarm}
              onReactivateFarm={onReactivateFarm}
              reactivating={reactivating}
              reactivateError={reactivateError}
            />
          ) : null}
          {tab === "defaults" ? <BlockDefaultsPanel farmId={farmId} farmName={farmName} /> : null}
          {tab === "members" ? <FarmMembersTab farmId={farmId} /> : null}
        </div>
      </aside>
    </>
  );
}

const settingsInput =
  "w-full rounded-lg border border-ap-line bg-ap-panel px-3 py-2 text-sm text-ap-ink focus:border-ap-primary focus:outline-none";
const WATER_SOURCES: WaterSource[] = ["well", "canal", "nile", "desalinated", "rainfed", "mixed"];

function FarmEditTab({
  farmId,
  canInactivate,
  onInactivateFarm,
  onReactivateFarm,
  reactivating,
  reactivateError,
}: {
  farmId: string;
  canInactivate: boolean;
  onInactivateFarm: () => void;
  onReactivateFarm: () => void;
  reactivating: boolean;
  reactivateError: string | null;
}): ReactNode {
  const { t } = useTranslation("farmConsole");
  const navigate = useNavigate();
  const qc = useQueryClient();
  const farmQ = useQuery({
    queryKey: ["labs/mapnext/farm", farmId],
    queryFn: () => getFarm(farmId),
    staleTime: 30_000,
  });
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
  if (farmQ.isError || !f)
    return <div className="text-sm text-ap-crit">{t("manage.editLoadError")}</div>;
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        mut.mutate(state);
      }}
    >
      <label className="mb-3 block">
        <span className="mb-1 block text-xs font-semibold text-ap-muted">
          {t("settingsFarm.name")}
        </span>
        <input
          className={settingsInput}
          value={state.name ?? ""}
          onChange={(e) => set({ name: e.target.value })}
        />
      </label>
      <div className="grid grid-cols-2 gap-3">
        <label className="mb-3 block">
          <span className="mb-1 block text-xs font-semibold text-ap-muted">
            {t("settingsFarm.governorate")}
          </span>
          <input
            className={settingsInput}
            value={state.governorate ?? ""}
            onChange={(e) => set({ governorate: e.target.value || null })}
          />
        </label>
        <label className="mb-3 block">
          <span className="mb-1 block text-xs font-semibold text-ap-muted">
            {t("settingsFarm.district")}
          </span>
          <input
            className={settingsInput}
            value={state.district ?? ""}
            onChange={(e) => set({ district: e.target.value || null })}
          />
        </label>
        <label className="mb-3 block">
          <span className="mb-1 block text-xs font-semibold text-ap-muted">
            {t("settingsFarm.city")}
          </span>
          <input
            className={settingsInput}
            value={state.nearest_city ?? ""}
            onChange={(e) => set({ nearest_city: e.target.value || null })}
          />
        </label>
        <label className="mb-3 block">
          <span className="mb-1 block text-xs font-semibold text-ap-muted">
            {t("settingsFarm.water")}
          </span>
          <select
            className={settingsInput}
            value={state.primary_water_source ?? ""}
            onChange={(e) =>
              set({ primary_water_source: (e.target.value || null) as WaterSource | null })
            }
          >
            <option value="">—</option>
            {WATER_SOURCES.map((w) => (
              <option key={w} value={w}>
                {w}
              </option>
            ))}
          </select>
        </label>
      </div>
      <label className="mb-3 block">
        <span className="mb-1 block text-xs font-semibold text-ap-muted">{t("manage.tags")}</span>
        <input
          className={settingsInput}
          value={(state.tags ?? []).join(", ")}
          onChange={(e) =>
            set({
              tags: e.target.value
                .split(",")
                .map((s) => s.trim())
                .filter(Boolean),
            })
          }
        />
      </label>
      {mut.isError ? (
        <div className="mb-2 text-xs text-ap-crit">{t("manage.saveError")}</div>
      ) : null}
      <div className="flex items-center gap-2">
        <button
          type="submit"
          disabled={mut.isPending}
          className="h-9 rounded-lg bg-ap-primary px-4 text-sm font-semibold text-white disabled:opacity-60"
        >
          {mut.isPending ? t("manage.saving") : t("manage.save")}
        </button>
        {mut.isSuccess && !form ? (
          <span className="text-xs text-ap-good">{t("settingsFarm.saved")}</span>
        ) : null}
        <button
          type="button"
          onClick={() => navigate(`/labs/map-legacy/${farmId}`)}
          className="ms-auto text-xs text-ap-muted underline hover:text-ap-ink"
        >
          {t("settingsFarm.editAoi")}
        </button>
      </div>

      {/* Danger zone — soft inactivation (no hard delete exists by design), and
          the way back for an already-inactive farm. Buttons are type="button",
          so they never submit the edit form above. */}
      {canInactivate ? (
        <section className="mt-7 rounded-xl border border-ap-crit/40 bg-ap-crit/5 p-4">
          <h3 className="text-sm font-bold text-ap-crit">{t("dangerZone.title")}</h3>
          <p className="mt-1 text-xs leading-relaxed text-ap-muted">
            {t("dangerZone.inactivateHint")}
          </p>
          {f.is_active ? (
            <button
              type="button"
              onClick={onInactivateFarm}
              className="mt-3 h-9 rounded-lg border border-ap-crit px-3.5 text-sm font-semibold text-ap-crit hover:bg-ap-crit hover:text-white"
            >
              {t("dangerZone.inactivateFarm")}
            </button>
          ) : (
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <span className="text-xs font-semibold text-ap-ink">
                {t("dangerZone.inactiveSince", { date: f.active_to ?? "—" })}
              </span>
              <button
                type="button"
                onClick={onReactivateFarm}
                disabled={reactivating}
                className="h-9 rounded-lg bg-ap-primary px-3.5 text-sm font-semibold text-white disabled:opacity-60"
              >
                {reactivating ? t("dangerZone.reactivating") : t("dangerZone.reactivate")}
              </button>
            </div>
          )}
          {reactivateError ? (
            <div className="mt-2 text-xs text-ap-crit">{reactivateError}</div>
          ) : null}
        </section>
      ) : null}
    </form>
  );
}

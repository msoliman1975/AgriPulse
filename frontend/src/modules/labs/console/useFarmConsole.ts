// Read orchestration for Farm Console v2 — every query the console issues
// and every value derived from them.
//
// Transcribed from modules/labs/mapnext/FarmConsolePage.tsx @ 7b7f7ba0.
// Before touching this file, run:
//   git log --oneline 7b7f7ba0..HEAD -- src/modules/labs/mapnext/FarmConsolePage.tsx
// and port anything you find. Both copies die when v1 is deleted at cutover.
//
// The duplication is deliberate: extracting a shared hook would mean
// refactoring the live console — 1,327 lines with no unit tests at all —
// to remove a duplication that deletes itself. See the plan's architecture
// note. What is duplicated here is `useState` and `useQuery` wiring; every
// piece of real logic still lives in the modules both consoles import
// (map/api.ts, api/grid.ts, gridOverlay.ts, signalOverlay.ts).
import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import type { FeatureCollection, Polygon } from "geojson";

import type { Block } from "@/api/blocks";
import { getFarmGridCells, getGridCells } from "@/api/grid";
import { listFarmScenes, listSubscriptions } from "@/api/imagery";
import { getIndexCatalog, type AnyIndexCode as ApiIndexCode } from "@/api/indices";
import { listSignalDefinitions, listSignalObservations } from "@/api/signals";
import { useAlerts } from "@/queries/alerts";
import { useRecommendations } from "@/queries/recommendations";
import type { CellItem } from "@/modules/grid/GridCellPopup";
import {
  loadBlockHealth,
  loadMapSummary,
  loadUnitDetail,
  mapWithConcurrency,
  toUnitIntegration,
} from "../map/api";
import type { GridCellProps } from "../map/MapCanvas";
import { blockCentroidsFromGeojson, buildSignalOverlay } from "../map/signalOverlay";
import { griddedBlocks } from "../mapnext/gridOverlay";
import { isThermalIndex, LAST_FARM_KEY } from "../mapnext/constants";
import { CONSOLE_QK } from "./constants";
import { classify } from "./indexClasses";
import { useIndexPixels } from "./useIndexPixels";
import { useOptionalConfig } from "@/config/ConfigContext";
import type { LayerState } from "../mapnext/ViewBar";

export function useFarmConsole(farmId: string) {
  const { i18n } = useTranslation("farmConsole");
  const [search, setSearch] = useSearchParams();
  const selectedId = search.get("unit");
  const selectedObsId = search.get("signal_obs");
  // The scene the whole console is reading "as of". A date (not an instant)
  // in the URL, because that is the unit a grower thinks in and the unit the
  // strip is grouped by; it resolves to an instant via the scene list.
  const sceneDate = search.get("scene");

  // One index drives the map pixel layer, the block fill, the legend and the
  // dock's featured card. Declared before the scene queries because it scopes
  // them: an index names a product, and the two products this farm may carry
  // are acquired independently.
  const [activeIndex, setActiveIndex] = useState<ApiIndexCode>("ndvi");

  // Acquisition days across the farm. Degrades to "no timeline" rather than
  // erroring when the API predates the route.
  //
  // Scoped to the active index. The strip is what SELECTS a pass, so an
  // unscoped one is worse than cosmetic in both directions: it offers optical
  // dates while thermal is being drawn (no `lst.tif` behind them) and marks
  // every thermal date undrawable, because drawability used to be tested
  // against an `ndvi` aggregate a thermal pass will never write.
  const scenesQ = useQuery({
    queryKey: CONSOLE_QK.scenes(farmId, activeIndex),
    queryFn: () => listFarmScenes(farmId, activeIndex),
    staleTime: 5 * 60_000,
  });
  const scenes = useMemo(() => scenesQ.data?.items ?? [], [scenesQ.data]);
  const selectedScene = useMemo(
    () => (sceneDate ? (scenes.find((s) => s.scene_date === sceneDate) ?? null) : null),
    [scenes, sceneDate],
  );
  // No scene selected means "latest", which is what the grid route already
  // does when `at` is omitted — so send nothing rather than pinning to today.
  const sceneAt = selectedScene?.at ?? null;

  const [layers, setLayers] = useState<LayerState>({
    aoi: true,
    blocks: true,
    borders: true,
    labels: true,
    borderOpacity: 0.6,
    fillOpacity: 1,
  });
  // Grid overlay defaults ON for a farm that has any sub-block grid
  // configured — someone who went to the trouble of zoning a block wants to
  // see the zones without hunting through a menu. Latched after the first
  // summary so a later toggle-off is not undone by a refetch, and keyed per
  // farm so switching farms re-evaluates.
  const [showGrid, setShowGrid] = useState(false);
  const gridDefaultedFor = useRef<string | null>(null);
  // The index pixels are the map's primary reading of the farm, so they are on
  // by default wherever there is imagery. Separate from the grid toggle: the
  // mesh and the pixels answer different questions, and reading fine detail
  // means turning the mesh off over the pixels rather than losing both.
  const [showPixels, setShowPixels] = useState(true);
  const [selectedCellId, setSelectedCellId] = useState<string | null>(null);
  const [cellClickPoint, setCellClickPoint] = useState<{ x: number; y: number } | null>(null);
  const [signalDefId, setSignalDefId] = useState<string | null>(null);
  const [obsClickPoint, setObsClickPoint] = useState<{ x: number; y: number } | null>(null);

  useEffect(() => {
    if (typeof window !== "undefined") window.localStorage.setItem(LAST_FARM_KEY, farmId);
  }, [farmId]);

  const summaryQ = useQuery({
    queryKey: CONSOLE_QK.summary(farmId),
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
    queryKey: CONSOLE_QK.detail(farmId, selectedId, i18n.language),
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

  // Integration health rides its own query so it can never hold up the map;
  // it only feeds two rows in the dock, which fill in on arrival.
  const blockHealthQ = useQuery({
    queryKey: CONSOLE_QK.blockHealth(farmId),
    queryFn: () => loadBlockHealth(farmId),
    staleTime: 60_000,
  });
  const selectedIntegration = toUnitIntegration(
    selectedId ? (blockHealthQ.data?.[selectedId] ?? null) : null,
  );

  // Active imagery subscriptions across the whole farm. The legend needs it
  // to tell "no grid configured" apart from "no imagery to compute one from"
  // — on a freshly onboarded tenant every block has zero, and pointing that
  // user at grid configuration would send them somewhere that cannot help.
  // `null` means "not known yet", which is not the same as zero.
  const imagerySubCount = useMemo<number | null>(() => {
    if (!blockHealthQ.data) return null;
    return Object.values(blockHealthQ.data).reduce(
      (n, h) => n + (toUnitIntegration(h)?.imagery.active_subs ?? 0),
      0,
    );
  }, [blockHealthQ.data]);

  // First active imagery product for the selected block — needed for grid config.
  const subsQ = useQuery({
    queryKey: CONSOLE_QK.subs(selectedId),
    queryFn: () => listSubscriptions(selectedId as string, { include_inactive: false }),
    enabled: Boolean(selectedId),
    staleTime: 60_000,
  });
  const gridProductId = subsQ.data?.[0]?.product_id ?? null;

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

  // Farm-wide grid in ONE request. The per-block path stays as a fallback
  // because charts deploy independently, so a new frontend can meet an api
  // that has no farm route yet — bounded to 4 in flight so a degraded path
  // degrades rather than taking the connection pool down with it.
  const farmGridQ = useQuery({
    queryKey: CONSOLE_QK.farmGrid(farmId, activeIndex, overlayKey, sceneAt),
    queryFn: async () => {
      const farmWide = await getFarmGridCells(farmId, activeIndex, sceneAt ?? undefined);
      if (farmWide) {
        return farmWide.blocks.map((b) => ({
          blockId: b.block_id,
          productId: b.product_id,
          cells: b.cells,
        }));
      }
      // The per-block fallback must honour the scene too, or an old API
      // would silently serve "latest" while the timeline says otherwise.
      return mapWithConcurrency(gridded, 4, async ({ blockId, productId }) => {
        const res = await getGridCells(blockId, productId, activeIndex, sceneAt ?? undefined);
        return { blockId, productId, cells: res.cells };
      });
    },
    // Never issued for a thermal index, because it could only ever come back
    // empty: `grid_configs` are per-product, only the optical product has
    // one, and `list_cells_for_scene` filters on `cfg.product_id` — so the
    // write path never produces a thermal cell row and the read path could
    // not return one if it did. Sending the request anyway would spend a
    // round trip to draw nothing and leave the mesh looking broken rather
    // than inapplicable; `gridUnavailableForIndex` is what says which it is.
    enabled: Boolean(showGrid && gridded.length > 0 && !isThermalIndex(activeIndex)),
    staleTime: 30_000,
  });

  // The active index's display unit, for the legend and anything else that
  // renders a raw value. Platform-wide curated data, so it is cached across
  // every farm and index the reader visits and never gated on the farm; a
  // failure degrades to the dimensionless case, which was the only case
  // before `lst`. Read rather than hardcoded — a local code-to-unit table is
  // the mirror that drifts.
  const catalogQ = useQuery({
    queryKey: ["indices", "catalog"] as const,
    queryFn: getIndexCatalog,
    staleTime: 60 * 60_000,
  });
  const activeIndexUnit = useMemo(
    () => catalogQ.data?.find((entry) => entry.code === activeIndex)?.unit ?? "",
    [catalogQ.data, activeIndex],
  );

  // Sub-block zoning exists on this farm, but not for what is being drawn.
  // A distinct state from "no grid configured": the toggle stays meaningful,
  // it is this index that cannot honour it.
  const gridUnavailableForIndex = isThermalIndex(activeIndex) && gridded.length > 0;

  // Index pixels + the statistics that feed the legend and the block fill.
  // Not gated on `showPixels`: the block fill and the legend read the same
  // numbers, so turning the layer off must not empty the panel.
  // Block extents for the pixel sources. Each COG covers one block and the
  // tile server 404s outside it, so an unbounded source asks four times for
  // every tile and throws away three answers.
  const boundsByBlockId = useMemo(() => {
    const m = new Map<string, [number, number, number, number]>();
    for (const f of summaryQ.data?.geojson.features ?? []) {
      let w = Infinity;
      let s = Infinity;
      let e = -Infinity;
      let n = -Infinity;
      for (const ring of f.geometry.coordinates) {
        for (const [x, y] of ring) {
          if (x < w) w = x;
          if (y < s) s = y;
          if (x > e) e = x;
          if (y > n) n = y;
        }
      }
      if (Number.isFinite(w)) m.set(f.properties.id, [w, s, e, n]);
    }
    return m;
  }, [summaryQ.data]);

  // The farm's own extent, for the single-source path. Same reason blocks are
  // bounded: the tile server 404s outside the raster, so an unbounded source
  // asks for tiles that cannot exist.
  const farmBounds = useMemo<[number, number, number, number] | null>(() => {
    const boundary = summaryQ.data?.farm.boundary;
    if (!boundary) return null;
    let w = Infinity;
    let s2 = Infinity;
    let e = -Infinity;
    let n = -Infinity;
    for (const poly of boundary.coordinates) {
      for (const ring of poly) {
        for (const [x, y] of ring) {
          if (x < w) w = x;
          if (y < s2) s2 = y;
          if (x > e) e = x;
          if (y > n) n = y;
        }
      }
    }
    return Number.isFinite(w) ? [w, s2, e, n] : null;
  }, [summaryQ.data]);

  const { config } = useOptionalConfig();
  const pixels = useIndexPixels({
    farmId,
    code: activeIndex,
    sceneAt,
    config,
    boundsByBlockId,
    farmBounds,
    farmAreaM2: summaryQ.data?.farm.area_m2 ?? null,
    enabled: Boolean(config),
  });

  // Blocks carry the colour of their own class, so the map has one colour
  // language whether or not the pixels are drawn. Injected as a feature
  // property rather than resolved inside MapCanvas, which stays unaware of
  // what an index class is.
  const geojsonWithClasses = useMemo(() => {
    const base = summaryQ.data?.geojson;
    if (!base) return base;
    return {
      ...base,
      features: base.features.map((f) => {
        const mean = pixels.meanByBlockId.get(f.properties.id);
        const cls = mean === undefined ? null : classify(activeIndex, mean);
        return cls
          ? { ...f, properties: { ...f.properties, class_color: cls.color } }
          : // No property at all, not a transparent colour: the paint
            // expression keys off `has`, so an absent block reads as "no
            // reading" rather than as a class that happens to be invisible.
            f;
      }),
    };
  }, [summaryQ.data, pixels.meanByBlockId, activeIndex]);

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

  // Cell-scoped outputs: open recs + alerts for the farm, grouped by the cell
  // they were attributed to, so the grid popup can say what is happening here.
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
    queryKey: CONSOLE_QK.signalDefs(),
    queryFn: () => listSignalDefinitions(),
    staleTime: 5 * 60_000,
  });
  const signalObsQ = useQuery({
    queryKey: CONSOLE_QK.signalObs(farmId, signalDefId),
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

  // ---- selection -----------------------------------------------------------
  const select = (id: string): void => {
    const next = new URLSearchParams(search);
    next.set("unit", id);
    next.delete("signal_obs");
    setSearch(next, { replace: false });
    setSelectedCellId(null);
  };
  const deselect = (): void => {
    const next = new URLSearchParams(search);
    next.delete("unit");
    setSearch(next, { replace: false });
  };
  const selectObservation = (observationId: string, point: { x: number; y: number }): void => {
    const next = new URLSearchParams(search);
    next.set("signal_obs", observationId);
    setSearch(next, { replace: true });
    setObsClickPoint(point);
    setSelectedCellId(null);
  };
  const clearObservation = (): void => {
    const next = new URLSearchParams(search);
    next.delete("signal_obs");
    setSearch(next, { replace: true });
    setObsClickPoint(null);
  };
  const selectScene = (scene_date: string | null): void => {
    const next = new URLSearchParams(search);
    if (scene_date) next.set("scene", scene_date);
    else next.delete("scene");
    setSearch(next, { replace: true });
    setSelectedCellId(null);
  };
  const changeSignalDef = (id: string | null): void => {
    setSignalDefId(id);
    const next = new URLSearchParams(search);
    next.delete("signal_obs");
    setSearch(next, { replace: true });
  };

  return {
    // url + view state
    search,
    setSearch,
    selectedId,
    selectedObsId,
    activeIndex,
    setActiveIndex,
    layers,
    setLayers,
    showGrid,
    setShowGrid,
    gridUnavailableForIndex,
    activeIndexUnit,
    showPixels,
    setShowPixels,
    selectedCellId,
    setSelectedCellId,
    cellClickPoint,
    setCellClickPoint,
    signalDefId,
    changeSignalDef,
    obsClickPoint,
    // scenes
    scenesQ,
    scenes,
    sceneDate,
    sceneAt,
    selectedScene,
    selectScene,
    medianGapDays: scenesQ.data?.median_gap_days ?? null,
    // queries
    summaryQ,
    detailQ,
    blockHealthQ,
    subsQ,
    farmGridQ,
    signalDefsQ,
    signalObsQ,
    // derived
    blocksById,
    blockNameById,
    selectedIntegration,
    imagerySubCount,
    gridProductId,
    gridded,
    gridCellsFc,
    pixels,
    geojsonWithClasses,
    cellMeta,
    highlightedCellIds,
    selectedCellBaseline,
    cellItemsByCell,
    selectedSignalDef,
    signalOverlayFc,
    selectedObs,
    // actions
    select,
    deselect,
    selectObservation,
    clearObservation,
  };
}

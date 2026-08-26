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
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { localizedName } from "@/lib/localizedField";
import type { FeatureCollection, Polygon } from "geojson";

import type { Block } from "@/api/blocks";
import { listFarmCropAssignments } from "@/api/cropAssignments";
import { listFieldFlags } from "@/api/fieldFlags";
import { getFarmGridCells, getGridCells } from "@/api/grid";
import { listFarmScenes, listSubscriptions } from "@/api/imagery";
import { getIndexCatalog, type AnyIndexCode as ApiIndexCode } from "@/api/indices";
import {
  listSignalDefinitions,
  listSignalObservations,
  type SignalObservation,
} from "@/api/signals";
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
import { buildFlagOverlay } from "../map/flagOverlay";
import { blockCentroidsFromGeojson, buildSignalOverlay } from "../map/signalOverlay";
import { cropLabel } from "../mapnext/dockFormat";
import { griddedBlocks } from "../mapnext/gridOverlay";
import { isThermalIndex, LAST_FARM_KEY } from "../mapnext/constants";
import { CONSOLE_QK } from "./constants";
import { asOfInstant, scenesWithin, TIMELINE_DEFAULT_DAYS } from "./timelineWindow";
import { classify } from "./indexClasses";
import { useIndexPixels } from "./useIndexPixels";
import { useOptionalConfig } from "@/config/ConfigContext";
import type { LayerState } from "../mapnext/ViewBar";
import type { FlagsMode } from "./MapDataControl";

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

  // The instant the whole console reads the farm "as of".
  //
  // The map is a picture of one day. Scrubbing back to a pass from ten days
  // ago and still seeing a flag a scout raised yesterday, or an alert that
  // opened this morning, makes the map disagree with its own date bar — the
  // reader cannot tell which marks belong to the scene they are looking at.
  //
  // The END of the selected day, not `scene.at`: the satellite passes in the
  // morning, and cutting at the overpass instant would hide everything
  // recorded later the same day, which nobody means by "on the 12th".
  // Null while the timeline is on "latest", which reads as "now".
  const asOf = asOfInstant(sceneDate);

  // How far back the date bar opens. 30 days rather than the whole history:
  // a farm with two years of Sentinel-2 has ~180 passes, and a strip that
  // long opens scrolled to one end with no sense of where the reader is.
  // `null` means every pass the api returned.
  const [timelineDays, setTimelineDays] = useState<number | null>(TIMELINE_DEFAULT_DAYS);

  // The window the strip actually draws. See timelineWindow.ts for the two
  // rules that decide it.
  const visibleScenes = useMemo(
    () => scenesWithin(scenes, timelineDays, sceneDate),
    [scenes, timelineDays, sceneDate],
  );

  const [layers, setLayers] = useState<LayerState>({
    aoi: true,
    blocks: true,
    borders: true,
    labels: true,
    borderOpacity: 0.6,
    fillOpacity: 1,
    // Both consoles share ViewBar, so both must actually serve the toggle it
    // draws. Wiring only one would leave a control here that does nothing —
    // the exact drift that let cell size go missing from a console before.
    flags: true,
    // "Current" — open flags only. The tri-state picker in the datapoint
    // control makes the other two reachable in one click, and a map opening
    // on every flag ever raised buries the ones somebody is waiting on.
    flagsOpenOnly: true,
    signals: true,
    // Block name, not crop: the name is what the rail, the dock and every
    // link in the console call a block, so the map agrees with them until
    // somebody asks it not to.
    labelField: "name",
    // Alert chips on by default — the map's job is to say where the trouble
    // is before anyone asks.
    alerts: true,
    // The mark legend starts hidden. It is a reference, and it costs a row of
    // the map every time it is open.
    markLegend: false,
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
  // Every observation on the coordinate that was last clicked, newest first.
  // One mark can stand for several readings — entity-mode observations all
  // resolve to their block's centroid — so the panel needs the list to let a
  // reader walk them instead of seeing only the newest.
  const [obsStack, setObsStack] = useState<string[]>([]);

  useEffect(() => {
    if (typeof window !== "undefined") window.localStorage.setItem(LAST_FARM_KEY, farmId);
  }, [farmId]);

  const summaryQ = useQuery({
    queryKey: CONSOLE_QK.summary(farmId, asOf),
    queryFn: () => loadMapSummary(farmId, asOf),
    staleTime: 30_000,
    refetchInterval: 60_000,
    // Hold the previous answer while the next one loads.
    //
    // Load-bearing, not a nicety. The page renders a full-screen "loading
    // this farm" branch whenever `summaryQ.data` is absent, and adding the
    // as-of instant to this key means every click on the date bar is a new
    // key with no cached data. Without this the whole console unmounts on
    // each date — map included — and the map re-frames the farm when it comes
    // back. The console's one rule is that the map never unmounts.
    //
    // The stale answer is also very nearly right: `at` changes the alert
    // rollup only. The block roster and the geometry are the same farm.
    placeholderData: keepPreviousData,
  });

  const blocksById = useMemo(() => {
    const m = new Map<string, Block>();
    for (const b of summaryQ.data?.blocks ?? []) m.set(b.id, b);
    return m;
  }, [summaryQ.data]);

  const blockNameById = useMemo(() => {
    const m = new Map<string, string>();
    for (const b of summaryQ.data?.blocks ?? [])
      m.set(b.id, localizedName(i18n.language, b.name?.trim() || b.code, b.name_ar));
    return m;
  }, [summaryQ.data, i18n.language]);

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
  /**
   * Which index the mesh is FETCHED with, which is not the one being drawn.
   *
   * The cells are geometry. Their outlines are identical whatever the map is
   * painting, and this console never fills them (`gridFillVisible={false}`) —
   * so the index here only decides which product's cell rows come back.
   * Thermal has no grid config, so asking with a thermal code returns nothing
   * and the mesh disappears; asking with "None" cannot ask at all. Both used
   * to grey out the Cells box, which made a farm's zoning look absent because
   * of what was being drawn over it.
   *
   * `ndvi` is the fallback because it is the optical product every gridded
   * farm has. The cell VALUES that come back are that index's, so the popup
   * is told this code rather than the one on the rail.
   */
  const gridIndex: ApiIndexCode = isThermalIndex(activeIndex) ? "ndvi" : activeIndex;

  const farmGridQ = useQuery({
    queryKey: CONSOLE_QK.farmGrid(farmId, gridIndex, overlayKey, sceneAt),
    queryFn: async () => {
      const farmWide = await getFarmGridCells(farmId, gridIndex, sceneAt ?? undefined);
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
        const res = await getGridCells(blockId, productId, gridIndex, sceneAt ?? undefined);
        return { blockId, productId, cells: res.cells };
      });
    },
    // Issued whenever the farm has zoning and the mesh is switched on. It is
    // no longer gated on the index: `gridIndex` already resolves to a product
    // that can answer, so a thermal or "None" reading keeps its outlines.
    enabled: Boolean(showGrid && gridded.length > 0),
    staleTime: 30_000,
    // The mesh is drawn from this. Without it the cells vanish and come back
    // on every date change, which reads as the map reloading.
    placeholderData: keepPreviousData,
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
    // "None" in the index picker means the map draws no index at all — no
    // pixels and no class fill. Colouring the blocks anyway would leave the
    // reader looking at an index they had just switched off.
    if (!showPixels) return base;
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
  }, [summaryQ.data, pixels.meanByBlockId, activeIndex, showPixels]);

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
    // Both lists are filtered on `created_at` rather than fetched as-of: the
    // recommendation and alert routes have no time parameter, and the console
    // already holds the farm's open set. What the cell popup must not do is
    // attribute a card that opened this morning to a pass from last week.
    for (const r of cellRecsQ.data ?? []) {
      if (!r.cell_id) continue;
      if (asOf && r.created_at > asOf) continue;
      const text = (isAr && r.text_ar) || r.text_en;
      map.set(r.cell_id, [
        ...(map.get(r.cell_id) ?? []),
        { id: r.id, kind: "rec", severity: r.severity, text },
      ]);
    }
    for (const a of cellAlertsQ.data ?? []) {
      if (!a.cell_id) continue;
      if (asOf && a.created_at > asOf) continue;
      const text = ((isAr && a.diagnosis_ar) || a.diagnosis_en) ?? a.rule_code;
      map.set(a.cell_id, [
        ...(map.get(a.cell_id) ?? []),
        { id: a.id, kind: "alert", severity: a.severity, text },
      ]);
    }
    return map;
  }, [cellRecsQ.data, cellAlertsQ.data, isAr, asOf]);

  // Signal overlay: definitions for the picker + observations for the active one.
  const signalDefsQ = useQuery({
    queryKey: CONSOLE_QK.signalDefs(),
    queryFn: () => listSignalDefinitions(),
    staleTime: 5 * 60_000,
  });
  // One fetch for the whole farm, not one per signal definition. The layer
  // shows every signal type at once, and re-fetching on every pick would
  // spend a round trip to narrow a list the client already holds.
  const signalObsQ = useQuery({
    queryKey: CONSOLE_QK.signalObs(farmId, asOf),
    queryFn: () =>
      listSignalObservations({
        farm_id: farmId,
        limit: 500,
        // Server-side, because `until` is a real parameter on this route and
        // the 500-row cap would otherwise be spent on readings the map is
        // about to throw away.
        ...(asOf ? { until: asOf } : {}),
      }),
    enabled: Boolean(farmId && layers.signals),
    staleTime: 30_000,
    // Same reason as the summary: a date change is a new key, and without
    // this the marks disappear and come back on every click.
    placeholderData: keepPreviousData,
  });
  const pickedSignalDef = signalDefsQ.data?.find((d) => d.id === signalDefId) ?? null;
  const blockCentroids = useMemo(
    () =>
      summaryQ.data
        ? blockCentroidsFromGeojson(summaryQ.data.geojson)
        : new Map<string, [number, number]>(),
    [summaryQ.data],
  );
  const flagsQ = useQuery({
    queryKey: CONSOLE_QK.fieldFlags(farmId, layers.flagsOpenOnly, asOf),
    queryFn: () => listFieldFlags(farmId, { pinned_only: true, open_only: layers.flagsOpenOnly }),
    enabled: Boolean(farmId && layers.flags),
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  });
  const flagOverlayFc = useMemo(() => {
    if (!layers.flags) return null;
    if (!flagsQ.data) return { type: "FeatureCollection" as const, features: [] };
    // Filtered here, not in the request: `GET /farms/{id}/field-flags` takes
    // `open_only` and `pinned_only` and nothing about time. Client-side is
    // honest for this route — a farm's pinned flags are tens of rows, not
    // thousands — and the alternative is a map that shows a pin for work
    // nobody had reported yet on the day being drawn.
    const rows = asOf ? flagsQ.data.filter((f) => f.created_at <= asOf) : flagsQ.data;
    return buildFlagOverlay(rows, blockCentroids);
  }, [layers.flags, flagsQ.data, blockCentroids, asOf]);

  // Crop labels, as of the scene date.
  //
  // Farm-wide in one request, and only while the reader asked for crop
  // labels: a console on block names never issues it. The date matters —
  // scrubbing back to a pass from a past season must name the crop that was
  // in the ground then, not the one there today.
  const cropLabelsQ = useQuery({
    queryKey: CONSOLE_QK.cropLabels(farmId, sceneDate),
    queryFn: () => listFarmCropAssignments(farmId, sceneDate),
    enabled: Boolean(farmId && layers.labels && layers.labelField === "crop"),
    staleTime: 5 * 60_000,
    placeholderData: keepPreviousData,
  });
  const cropLabelByBlockId = useMemo(() => {
    const m = new Map<string, string>();
    for (const row of cropLabelsQ.data ?? []) {
      // The whole assignment, not just the crop: a farm growing three mango
      // varieties had every block labelled "Mango". Built with the same
      // helper the Block Dock uses, so the map and the dock never disagree
      // about what a block is planted with.
      const label = cropLabel({
        crop_name: isAr ? row.crop_name_ar : row.crop_name_en,
        variety_name: (isAr ? row.variety_name_ar : row.variety_name_en) ?? null,
        strain_name: (isAr ? row.strain_name_ar : row.strain_name_en) ?? null,
      });
      if (label) m.set(row.block_id, label);
    }
    return m;
  }, [cropLabelsQ.data, isAr]);

  /**
   * The collection the map actually draws.
   *
   * Crop labels are a feature property rather than a MapLibre expression over
   * some other source, because the label layer is one `text-field` over the
   * whole units source. Identity of the object matters: MapCanvas re-sets the
   * source data whenever this changes, so it is only rebuilt when a crop label
   * is genuinely in play.
   */
  const geojsonForMap = useMemo(() => {
    const base = geojsonWithClasses;
    if (!base) return base;
    if (layers.labelField !== "crop" || cropLabelByBlockId.size === 0) return base;
    return {
      ...base,
      features: base.features.map((f) => {
        const crop = cropLabelByBlockId.get(f.properties.id);
        // No property at all when this block had no crop on this date: the
        // label expression coalesces to the block name, so the block stays
        // identified instead of going blank.
        return crop ? { ...f, properties: { ...f.properties, crop_label: crop } } : f;
      }),
    };
  }, [geojsonWithClasses, layers.labelField, cropLabelByBlockId]);

  // Value kind per definition, so a mixed overlay labels each observation
  // against its OWN signal rather than against whichever one is picked.
  const valueKindByDefId = useMemo(
    () => new Map((signalDefsQ.data ?? []).map((d) => [d.id, d.value_kind])),
    [signalDefsQ.data],
  );

  const signalOverlayFc = useMemo(() => {
    if (!layers.signals) return null;
    if (!signalObsQ.data) return { type: "FeatureCollection" as const, features: [] };
    // The picker NARROWS the layer; it no longer reveals it. Every farm's
    // observations are fetched in one call and filtered here, so an operator
    // sees that a scout recorded something without first guessing which
    // signal they used.
    const rows = signalDefId
      ? signalObsQ.data.filter((o) => o.signal_definition_id === signalDefId)
      : signalObsQ.data;
    return buildSignalOverlay(rows, blockCentroids, {
      valueKindByDefinitionId: valueKindByDefId,
    }).features;
  }, [layers.signals, signalDefId, signalObsQ.data, blockCentroids, valueKindByDefId]);
  const selectedObs = useMemo(
    () =>
      selectedObsId && signalObsQ.data
        ? (signalObsQ.data.find((o) => o.id === selectedObsId) ?? null)
        : null,
    [selectedObsId, signalObsQ.data],
  );

  // The definition of the observation being SHOWN, not of the one the picker
  // happens to be narrowed to. The layer draws every signal type at once, so
  // the picker is usually on "all" and reading the definition off it left the
  // popup titled with a raw `signal_code` and no unit beside the value.
  const selectedSignalDef = useMemo(() => {
    if (selectedObs) {
      return signalDefsQ.data?.find((d) => d.id === selectedObs.signal_definition_id) ?? null;
    }
    return pickedSignalDef;
  }, [selectedObs, signalDefsQ.data, pickedSignalDef]);

  // The readings the clicked mark stands for, in the order the overlay stacked
  // them. Resolved against the same list the overlay was built from, so an id
  // that has since been filtered out simply drops rather than rendering a
  // blank chip.
  const selectedObsStack = useMemo(() => {
    if (obsStack.length < 2 || !signalObsQ.data) return [];
    const byId = new Map(signalObsQ.data.map((o) => [o.id, o]));
    return obsStack.map((id) => byId.get(id)).filter((o): o is SignalObservation => Boolean(o));
  }, [obsStack, signalObsQ.data]);

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
  const selectObservation = (
    observationId: string,
    point: { x: number; y: number },
    stackIds: string[] = [observationId],
  ): void => {
    const next = new URLSearchParams(search);
    next.set("signal_obs", observationId);
    setSearch(next, { replace: true });
    setObsClickPoint(point);
    setObsStack(stackIds);
    setSelectedCellId(null);
  };
  /** Move to another reading on the same spot, without moving the popup. */
  const showObservation = (observationId: string): void => {
    const next = new URLSearchParams(search);
    next.set("signal_obs", observationId);
    setSearch(next, { replace: true });
  };
  const clearObservation = (): void => {
    const next = new URLSearchParams(search);
    next.delete("signal_obs");
    setSearch(next, { replace: true });
    setObsClickPoint(null);
    setObsStack([]);
  };
  const selectScene = (scene_date: string | null): void => {
    const next = new URLSearchParams(search);
    if (scene_date) next.set("scene", scene_date);
    else next.delete("scene");
    setSearch(next, { replace: true });
    setSelectedCellId(null);
  };
  /**
   * The index picker, with "None" folded in.
   *
   * `activeIndex` stays set to the last real index even at "None", because
   * the rail, the block dock and the scene timeline all read it and none of
   * them is the map. What "None" turns off is the map's own drawing —
   * `showPixels` gates both the raster and the block class fill.
   */
  const selectedIndex: ApiIndexCode | null = showPixels ? activeIndex : null;
  const changeSelectedIndex = (code: ApiIndexCode | null): void => {
    if (code == null) {
      setShowPixels(false);
      return;
    }
    setActiveIndex(code);
    setShowPixels(true);
  };

  /**
   * Flags as one tri-state.
   *
   * Stored as the two booleans both consoles already share rather than as a
   * third field: "current" and "historical" are both ON, and a separate mode
   * field would be a second source of truth for the same layer.
   */
  const flagsMode: FlagsMode = !layers.flags
    ? "none"
    : layers.flagsOpenOnly
      ? "current"
      : "historical";
  const changeFlagsMode = (mode: FlagsMode): void => {
    setLayers((l) => ({ ...l, flags: mode !== "none", flagsOpenOnly: mode === "current" }));
  };

  const changeSignals = ({ on, defId }: { on: boolean; defId: string | null }): void => {
    setLayers((l) => ({ ...l, signals: on }));
    changeSignalDef(defId);
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
    activeIndexUnit,
    showPixels,
    setShowPixels,
    selectedCellId,
    setSelectedCellId,
    cellClickPoint,
    setCellClickPoint,
    signalDefId,
    changeSignalDef,
    changeSignals,
    selectedIndex,
    changeSelectedIndex,
    flagsMode,
    changeFlagsMode,
    obsClickPoint,
    obsStack,
    // scenes
    scenesQ,
    scenes,
    sceneDate,
    sceneAt,
    asOf,
    visibleScenes,
    timelineDays,
    setTimelineDays,
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
    gridIndex,
    gridCellsFc,
    pixels,
    geojsonWithClasses,
    geojsonForMap,
    cropLabelsQ,
    cellMeta,
    highlightedCellIds,
    selectedCellBaseline,
    cellItemsByCell,
    selectedSignalDef,
    signalOverlayFc,
    flagOverlayFc,
    selectedObs,
    selectedObsStack,
    // actions
    select,
    deselect,
    selectObservation,
    showObservation,
    clearObservation,
  };
}

import { useEffect, useRef } from "react";
import maplibregl, {
  type ExpressionSpecification,
  type GeoJSONSource,
  type LngLatBoundsLike,
  type Map as MlMap,
  type StyleSpecification,
} from "maplibre-gl";
import MapboxDraw from "@mapbox/mapbox-gl-draw";
import "maplibre-gl/dist/maplibre-gl.css";
import "@mapbox/mapbox-gl-draw/dist/mapbox-gl-draw.css";

import { HEALTH_FILL, HEALTH_FILL_OPACITY, HEALTH_STROKE } from "./health";
import { approxPolygonAreaM2, haversineMeters, polygonPerimeterM } from "./geo";
import type { SignalOverlayProps } from "./signalOverlay";
import type { UnitFeatureProps } from "./types";
import type { FeatureCollection, MultiPolygon, Point, Polygon } from "geojson";

// Block drawing produces a Polygon. Farm AOI drawing also produces a
// Polygon under the hood, but we wrap it into a single-polygon
// MultiPolygon at the page level when submitting. Pivot drawing uses
// a custom click-center + click-radius interaction (no mapbox-gl-draw)
// and emits {center, radius_m} via onPivotDrawn instead.
export type DrawTarget = "block" | "farm_aoi" | "pivot";

export interface PivotDrawResult {
  center_lat: number;
  center_lon: number;
  radius_m: number;
}

// Live progress emitted while a polygon draw is in flight. `vertices`
// counts the points the user has actually clicked (excludes the
// mouse-follow tail vertex that mapbox-gl-draw maintains internally).
export interface DrawProgress {
  vertices: number;
  areaM2: number;
  perimeterM: number;
  target: DrawTarget;
}

interface Props {
  geojson: FeatureCollection<Polygon, UnitFeatureProps>;
  farmBoundary?: MultiPolygon | null;
  selectedId: string | null;
  onSelect: (id: string) => void;
  fitBoundsKey: string; // pass farm ID; bumping it refits
  drawEnabled?: boolean;
  drawTarget?: DrawTarget;
  onPolygonDrawn?: (polygon: Polygon, areaM2: number, target: DrawTarget) => void;
  // Fires on every render tick while a polygon draw is in progress.
  // Null = no draw in progress (or draw just finished/cancelled).
  // Used by the page to render a live readout overlay.
  onDrawProgress?: (progress: DrawProgress | null) => void;
  onPivotDrawn?: (result: PivotDrawResult) => void;
  // When set, MapCanvas enters direct-select mode against the supplied
  // polygon so the user can drag vertices. Every edit emits the new
  // polygon via onReshape; the page commits on Save.
  reshapeBlock?: { id: string; boundary: Polygon } | null;
  onReshape?: (polygon: Polygon) => void;
  // Visibility / styling toggles from the page toolbar.
  showAoi?: boolean;
  showBlocks?: boolean;
  showBlockBorders?: boolean;
  showBlockLabels?: boolean;
  // 0..1 multiplier applied to AOI line opacity and block stroke opacity.
  borderOpacity?: number;
  // 0..1 multiplier applied to block fill opacity (on top of the
  // per-feature health-based opacity). 1 = full opacity (default).
  blockFillOpacity?: number;
  // CS-8: signal-observation overlay. `null` hides the layer; an FC
  // (possibly empty) shows it. Click on a marker fires onSignalClick
  // with the underlying observation id.
  signalOverlay?: FeatureCollection<Point, SignalOverlayProps> | null;
  onSignalClick?: (observationId: string) => void;
  // Sub-block grid overlay (PR-grid). `null` hides; an FC shows.
  // Each feature must carry { cell_id: string, value: number | null }
  // in its properties; the heatmap color ramp reads `value`, the click
  // handler reads `cell_id`.
  gridCells?: FeatureCollection<Polygon, GridCellProps> | null;
  onGridCellClick?: (cellId: string) => void;
  // G-2: cell ids to outline on the heatmap (the worst-N / alert-cited
  // cells), so a scout can see exactly where to go. Empty = none.
  highlightedCellIds?: string[];
}

export interface GridCellProps {
  cell_id: string;
  // -1 is the no-data sentinel — see GRID_FILL_LAYER's fill-color
  // expression. Callers should encode null observations as -1 when
  // building the FeatureCollection.
  value: number;
}

const SOURCE_ID = "units";
const FILL_LAYER = "units-fill";
const STROKE_LAYER = "units-stroke";
const SELECTED_LAYER = "units-selected";
const LABEL_LAYER = "units-label";
const LOGICAL_PIVOT_LAYER = "logical-pivot-ring";
const ALERT_BADGE_LAYER = "alert-badges";
const AOI_SOURCE_ID = "farm-aoi";
const AOI_FILL_LAYER = "farm-aoi-fill";
const AOI_LINE_LAYER = "farm-aoi-line";
// CS-8: signal-observation overlay. One source + one circle layer
// per active overlay; the map page swaps the source data when the
// operator picks a different signal definition.
const SIGNAL_SOURCE_ID = "signal-overlay";
const SIGNAL_CIRCLE_LAYER = "signal-overlay-circle";
const SIGNAL_HALO_LAYER = "signal-overlay-halo";
// Sub-block grid overlay layers.
const GRID_SOURCE_ID = "subblock-grid";
const GRID_FILL_LAYER = "subblock-grid-fill";
const GRID_LINE_LAYER = "subblock-grid-line";
const GRID_HIGHLIGHT_LAYER = "subblock-grid-highlight";

const AOI_STROKE = "#0ea5e9"; // cyan-500 — distinct from block strokes
const AOI_FILL = "#0ea5e9";
// Visually distinct from block fills + alert badges. Amber-500 chosen
// because the existing alert palette uses red/orange and we want the
// overlay to read as informational, not warning-level.
const SIGNAL_OVERLAY_COLOR = "#f59e0b";

const STYLE: StyleSpecification = {
  version: 8,
  glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
  sources: {
    satellite: {
      type: "raster",
      tiles: [
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      ],
      tileSize: 256,
      attribution:
        "Tiles © Esri — Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community",
      maxzoom: 19,
    },
  },
  layers: [
    { id: "background", type: "background", paint: { "background-color": "#b5ad8e" } },
    { id: "satellite", type: "raster", source: "satellite", paint: { "raster-opacity": 1 } },
  ],
};

// `["match", get-prop, val, expr, val, expr, ..., default]`
function healthMatch<T>(
  attr: keyof UnitFeatureProps,
  values: Record<string, T>,
  fallback: T,
): ExpressionSpecification {
  const arr: unknown[] = ["match", ["get", attr as string]];
  for (const [k, v] of Object.entries(values)) arr.push(k, v);
  arr.push(fallback);
  return arr as ExpressionSpecification;
}

export function MapCanvas({
  geojson,
  farmBoundary,
  selectedId,
  onSelect,
  fitBoundsKey,
  drawEnabled,
  drawTarget = "block",
  onPolygonDrawn,
  onDrawProgress,
  onPivotDrawn,
  reshapeBlock = null,
  onReshape,
  showAoi = true,
  showBlocks = true,
  showBlockBorders = true,
  showBlockLabels = true,
  borderOpacity = 0.9,
  blockFillOpacity = 1,
  signalOverlay = null,
  onSignalClick,
  gridCells = null,
  onGridCellClick,
  highlightedCellIds = [],
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MlMap | null>(null);
  const drawRef = useRef<MapboxDraw | null>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const onPolygonDrawnRef = useRef(onPolygonDrawn);
  onPolygonDrawnRef.current = onPolygonDrawn;
  const onDrawProgressRef = useRef(onDrawProgress);
  onDrawProgressRef.current = onDrawProgress;
  const drawTargetRef = useRef(drawTarget);
  drawTargetRef.current = drawTarget;
  const onPivotDrawnRef = useRef(onPivotDrawn);
  onPivotDrawnRef.current = onPivotDrawn;
  const onReshapeRef = useRef(onReshape);
  onReshapeRef.current = onReshape;
  const onSignalClickRef = useRef(onSignalClick);
  onSignalClickRef.current = onSignalClick;
  const onGridCellClickRef = useRef(onGridCellClick);
  onGridCellClickRef.current = onGridCellClick;

  // Initial mount.
  useEffect(() => {
    if (!containerRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: STYLE,
      center: [31.0, 30.5],
      zoom: 14,
      attributionControl: { compact: true },
    });
    mapRef.current = map;
    map.dragRotate.disable();
    map.touchZoomRotate.disableRotation();

    map.on("load", () => {
      // Farm AOI source + layers — placed first so block layers render above.
      map.addSource(AOI_SOURCE_ID, {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: AOI_FILL_LAYER,
        type: "fill",
        source: AOI_SOURCE_ID,
        paint: {
          "fill-color": AOI_FILL,
          "fill-opacity": 0.06,
        },
      });
      map.addLayer({
        id: AOI_LINE_LAYER,
        type: "line",
        source: AOI_SOURCE_ID,
        paint: {
          "line-color": AOI_STROKE,
          "line-width": 2,
          "line-dasharray": [3, 2],
          "line-opacity": 0.9,
        },
      });

      map.addSource(SOURCE_ID, {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });

      // Fill layer — clickable, color-coded by health. Logical pivots are
      // excluded by filter. Future-dated blocks render at half opacity to
      // signal they aren't operational yet.
      map.addLayer({
        id: FILL_LAYER,
        type: "fill",
        source: SOURCE_ID,
        filter: ["!=", ["get", "is_logical_pivot"], true],
        paint: {
          "fill-color": healthMatch("health", HEALTH_FILL, HEALTH_FILL.unknown),
          "fill-opacity": [
            "case",
            ["==", ["get", "is_future"], true],
            0.25,
            healthMatch("health", HEALTH_FILL_OPACITY, HEALTH_FILL_OPACITY.unknown),
          ],
        },
      });

      map.addLayer({
        id: STROKE_LAYER,
        type: "line",
        source: SOURCE_ID,
        filter: [
          "all",
          ["!=", ["get", "is_logical_pivot"], true],
          ["!=", ["get", "is_future"], true],
        ],
        paint: {
          "line-color": healthMatch("health", HEALTH_STROKE, HEALTH_STROKE.unknown),
          "line-width": 1.2,
          "line-opacity": 0.9,
        },
      });
      // Future-dated blocks: same color but dashed so the operator can
      // tell something is coming on a specific future date.
      map.addLayer({
        id: STROKE_LAYER + "-future",
        type: "line",
        source: SOURCE_ID,
        filter: [
          "all",
          ["!=", ["get", "is_logical_pivot"], true],
          ["==", ["get", "is_future"], true],
        ],
        paint: {
          "line-color": healthMatch("health", HEALTH_STROKE, HEALTH_STROKE.unknown),
          "line-width": 1.2,
          "line-opacity": 0.7,
          "line-dasharray": [3, 2],
        },
      });

      map.addLayer({
        id: SELECTED_LAYER,
        type: "line",
        source: SOURCE_ID,
        filter: ["==", ["get", "id"], ""],
        paint: {
          "line-color": "#1a1916",
          "line-width": 3,
        },
      });

      // Logical pivot dashed ring on top, non-clickable.
      map.addLayer({
        id: LOGICAL_PIVOT_LAYER,
        type: "line",
        source: SOURCE_ID,
        filter: ["==", ["get", "is_logical_pivot"], true],
        paint: {
          "line-color": "#1a1916",
          "line-width": 1.2,
          "line-dasharray": [4, 3],
          "line-opacity": 0.55,
        },
      });

      // Unit labels — keep cheap; just the short name.
      map.addLayer({
        id: LABEL_LAYER,
        type: "symbol",
        source: SOURCE_ID,
        filter: ["!=", ["get", "is_logical_pivot"], true],
        layout: {
          "text-field": ["get", "name"],
          "text-size": 12,
          "text-allow-overlap": false,
        },
        paint: {
          "text-color": "#1a1916",
          "text-halo-color": "rgba(255,255,255,0.85)",
          "text-halo-width": 1.5,
        },
      });

      // Alert badges — circles with severity-driven size.
      map.addLayer({
        id: ALERT_BADGE_LAYER,
        type: "circle",
        source: SOURCE_ID,
        filter: ["==", ["get", "has_alert"], true],
        paint: {
          "circle-color": [
            "match",
            ["get", "alert_severity"],
            "critical",
            "#A32D2D",
            "watch",
            "#854F0B",
            "#999999",
          ],
          "circle-radius": ["match", ["get", "alert_severity"], "critical", 10, "watch", 8, 6],
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 1.5,
          "circle-translate": [12, -12],
        },
      });

      // CS-8: signal overlay source + two layers. The halo is a wider
      // semi-transparent ring under the solid circle so markers stay
      // visible against satellite imagery without dominating the map.
      map.addSource(SIGNAL_SOURCE_ID, {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: SIGNAL_HALO_LAYER,
        type: "circle",
        source: SIGNAL_SOURCE_ID,
        paint: {
          "circle-color": SIGNAL_OVERLAY_COLOR,
          "circle-radius": 10,
          "circle-opacity": 0.25,
        },
      });
      map.addLayer({
        id: SIGNAL_CIRCLE_LAYER,
        type: "circle",
        source: SIGNAL_SOURCE_ID,
        paint: {
          "circle-color": SIGNAL_OVERLAY_COLOR,
          "circle-radius": 5,
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 1.5,
        },
      });

      map.on("mousemove", FILL_LAYER, () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", FILL_LAYER, () => {
        map.getCanvas().style.cursor = "";
      });
      map.on("mousemove", SIGNAL_CIRCLE_LAYER, () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", SIGNAL_CIRCLE_LAYER, () => {
        map.getCanvas().style.cursor = "";
      });

      // Sub-block grid overlay (PR-grid). Heatmap colour ramp uses a
      // simple linear interpolation on the `value` property — null
      // values render as a neutral grey so "no data" cells are still
      // visible against the satellite base.
      map.addSource(GRID_SOURCE_ID, {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: GRID_FILL_LAYER,
        type: "fill",
        source: GRID_SOURCE_ID,
        paint: {
          // Null values are encoded as -1 on the FC-build side so this
          // expression never has to compare against null (MapLibre's
          // TS typing rejects `null` as an ExpressionInputType).
          "fill-color": [
            "interpolate",
            ["linear"],
            ["to-number", ["get", "value"]],
            -1,
            "#9ca3af", // slate-400 — "no data" sentinel
            0.0,
            "#dc2626", // red-600 — very low (bare/water)
            0.3,
            "#f59e0b", // amber-500 — stressed
            0.6,
            "#84cc16", // lime-500 — moderate
            0.85,
            "#16a34a", // green-600 — healthy
          ],
          "fill-opacity": 0.6,
        },
      });
      map.addLayer({
        id: GRID_LINE_LAYER,
        type: "line",
        source: GRID_SOURCE_ID,
        paint: {
          "line-color": "#1f2937",
          "line-width": 0.3,
          "line-opacity": 0.4,
        },
      });
      // G-2: bright outline over the worst-N / alert-cited cells. Starts
      // matching nothing; the highlightedCellIds effect swaps the filter.
      map.addLayer({
        id: GRID_HIGHLIGHT_LAYER,
        type: "line",
        source: GRID_SOURCE_ID,
        filter: ["in", ["get", "cell_id"], ["literal", []]],
        paint: {
          "line-color": "#db2777", // pink-600 — pops against the heatmap ramp
          "line-width": 2.5,
          "line-opacity": 0.95,
        },
      });
      map.on("mousemove", GRID_FILL_LAYER, () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", GRID_FILL_LAYER, () => {
        map.getCanvas().style.cursor = "";
      });

      map.on("click", FILL_LAYER, (ev) => {
        const f = ev.features?.[0];
        if (!f) return;
        const props = f.properties as Pick<UnitFeatureProps, "id">;
        onSelectRef.current(props.id);
      });
      map.on("click", GRID_FILL_LAYER, (ev) => {
        const f = ev.features?.[0];
        if (!f) return;
        const props = f.properties as { cell_id?: string };
        if (props.cell_id) onGridCellClickRef.current?.(props.cell_id);
      });
      map.on("click", SIGNAL_CIRCLE_LAYER, (ev) => {
        const f = ev.features?.[0];
        if (!f) return;
        const props = f.properties as { observation_id?: string };
        if (props.observation_id) {
          onSignalClickRef.current?.(props.observation_id);
        }
      });
    });

    return () => {
      if (drawRef.current) {
        try {
          map.removeControl(drawRef.current as unknown as maplibregl.IControl);
        } catch {
          /* ignore */
        }
        drawRef.current = null;
      }
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // Push GeoJSON data + fit bounds whenever data changes.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = () => {
      // tsc -b cannot narrow maplibre-gl's Source to GeoJSONSource for
      // .setData; eslint thinks it can. Tsc wins — keep the cast.
      // eslint-disable-next-line @typescript-eslint/no-unnecessary-type-assertion
      const src = map.getSource(SOURCE_ID) as GeoJSONSource | undefined;
      if (!src) return;
      src.setData(geojson);
      const bounds = computeBounds(geojson, farmBoundary ?? null);
      if (bounds) map.fitBounds(bounds, { padding: 40, duration: 600 });
    };
    if (map.isStyleLoaded()) apply();
    else map.once("load", apply);
  }, [geojson, fitBoundsKey, farmBoundary]);

  // Push AOI data whenever the farm boundary changes.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = () => {
      // See SOURCE_ID note above — tsc requires the cast, eslint thinks it's redundant.
      // eslint-disable-next-line @typescript-eslint/no-unnecessary-type-assertion
      const src = map.getSource(AOI_SOURCE_ID) as GeoJSONSource | undefined;
      if (!src) return;
      if (!farmBoundary) {
        src.setData({ type: "FeatureCollection", features: [] });
        return;
      }
      src.setData({
        type: "FeatureCollection",
        features: [
          {
            type: "Feature",
            geometry: farmBoundary,
            properties: {},
          },
        ],
      });
    };
    if (map.isStyleLoaded()) apply();
    else map.once("load", apply);
  }, [farmBoundary]);

  // CS-8: push signal overlay data + toggle visibility. `null` ⇒
  // hide; an empty FC ⇒ visible-but-empty (clears any stale markers
  // from a previous picker selection).
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = () => {
      // eslint-disable-next-line @typescript-eslint/no-unnecessary-type-assertion
      const src = map.getSource(SIGNAL_SOURCE_ID) as GeoJSONSource | undefined;
      if (!src) return;
      const visible = signalOverlay !== null;
      const fc = signalOverlay ?? { type: "FeatureCollection", features: [] };
      src.setData(fc);
      for (const layerId of [SIGNAL_CIRCLE_LAYER, SIGNAL_HALO_LAYER]) {
        if (!map.getLayer(layerId)) continue;
        map.setLayoutProperty(layerId, "visibility", visible ? "visible" : "none");
      }
    };
    if (map.isStyleLoaded()) apply();
    else map.once("load", apply);
  }, [signalOverlay]);

  // Sub-block grid overlay. Same null = hide / FC = show pattern as
  // signal overlay; data goes straight into the existing GeoJSON
  // source.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = () => {
      // eslint-disable-next-line @typescript-eslint/no-unnecessary-type-assertion
      const src = map.getSource(GRID_SOURCE_ID) as GeoJSONSource | undefined;
      if (!src) return;
      const visible = gridCells !== null;
      const fc = gridCells ?? { type: "FeatureCollection", features: [] };
      src.setData(fc);
      for (const layerId of [GRID_FILL_LAYER, GRID_LINE_LAYER, GRID_HIGHLIGHT_LAYER]) {
        if (!map.getLayer(layerId)) continue;
        map.setLayoutProperty(layerId, "visibility", visible ? "visible" : "none");
      }
    };
    if (map.isStyleLoaded()) apply();
    else map.once("load", apply);
  }, [gridCells]);

  // G-2: outline the cited cells (worst-N / alert) via a filter swap on
  // the highlight layer — same lightweight pattern as the block selection
  // highlight. An empty list matches nothing.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = () => {
      if (!map.getLayer(GRID_HIGHLIGHT_LAYER)) return;
      map.setFilter(GRID_HIGHLIGHT_LAYER, [
        "in",
        ["get", "cell_id"],
        ["literal", highlightedCellIds],
      ]);
    };
    if (map.isStyleLoaded()) apply();
    else map.once("load", apply);
  }, [highlightedCellIds]);

  // Visibility + opacity toggles. Each prop maps to one or two MapLibre
  // layers; if a layer hasn't been added yet (style still loading) we
  // skip silently and a later render will catch up via the data effect.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = () => {
      const setVis = (layerId: string, visible: boolean) => {
        if (!map.getLayer(layerId)) return;
        map.setLayoutProperty(layerId, "visibility", visible ? "visible" : "none");
      };
      setVis(AOI_FILL_LAYER, !!showAoi);
      setVis(AOI_LINE_LAYER, !!showAoi);
      // showBlocks is the master toggle — when off, every block-derived
      // layer (fill, strokes, labels, alert badges, logical-pivot ring)
      // hides so the operator sees only the base map + AOI border.
      setVis(FILL_LAYER, !!showBlocks);
      setVis(SELECTED_LAYER, !!showBlocks);
      setVis(ALERT_BADGE_LAYER, !!showBlocks);
      setVis(STROKE_LAYER, !!showBlocks && !!showBlockBorders);
      setVis(STROKE_LAYER + "-future", !!showBlocks && !!showBlockBorders);
      setVis(LOGICAL_PIVOT_LAYER, !!showBlocks && !!showBlockBorders);
      setVis(LABEL_LAYER, !!showBlocks && !!showBlockLabels);

      const op = Math.max(0, Math.min(1, borderOpacity));
      if (map.getLayer(AOI_LINE_LAYER)) {
        map.setPaintProperty(AOI_LINE_LAYER, "line-opacity", 0.9 * op);
      }
      if (map.getLayer(STROKE_LAYER)) {
        map.setPaintProperty(STROKE_LAYER, "line-opacity", 0.9 * op);
      }
      if (map.getLayer(STROKE_LAYER + "-future")) {
        map.setPaintProperty(STROKE_LAYER + "-future", "line-opacity", 0.7 * op);
      }

      // Block fill opacity: multiply the per-health base by the
      // operator's chosen multiplier. Future-dated blocks keep their
      // own halved opacity (0.25) so the future-vs-current distinction
      // survives the slider.
      const fillMul = Math.max(0, Math.min(1, blockFillOpacity));
      if (map.getLayer(FILL_LAYER)) {
        const scaledHealth: ExpressionSpecification = [
          "*",
          fillMul,
          healthMatch("health", HEALTH_FILL_OPACITY, HEALTH_FILL_OPACITY.unknown),
        ] as unknown as ExpressionSpecification;
        map.setPaintProperty(FILL_LAYER, "fill-opacity", [
          "case",
          ["==", ["get", "is_future"], true],
          0.25 * fillMul,
          scaledHealth,
        ] as ExpressionSpecification);
      }
    };
    if (map.isStyleLoaded()) apply();
    else map.once("load", apply);
  }, [showAoi, showBlocks, showBlockBorders, showBlockLabels, borderOpacity, blockFillOpacity]);

  // Selection highlight via filter swap.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = () => {
      if (!map.getLayer(SELECTED_LAYER)) return;
      map.setFilter(SELECTED_LAYER, ["==", ["get", "id"], selectedId ?? ""]);
    };
    if (map.isStyleLoaded()) apply();
    else map.once("load", apply);
  }, [selectedId]);

  // Draw mode toggling for polygon-shaped targets (block + farm AOI).
  // mapbox-gl-draw is added as a control while enabled and removed once
  // the user exits. Pivot mode is handled in a separate effect below
  // because its UX is center+radius rather than freehand polygon.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const usePolygonDraw = drawEnabled && drawTarget !== "pivot";
    if (!usePolygonDraw) {
      if (drawRef.current) {
        try {
          map.removeControl(drawRef.current as unknown as maplibregl.IControl);
        } catch {
          /* ignore */
        }
        drawRef.current = null;
      }
      return;
    }
    const draw = new MapboxDraw({
      displayControlsDefault: false,
      controls: { polygon: true, trash: true },
      defaultMode: "draw_polygon",
    });
    drawRef.current = draw;
    map.addControl(draw as unknown as maplibregl.IControl, "top-left");

    const onCreate = (evt: { features: GeoJSON.Feature[] }) => {
      const f = evt.features[0];
      if (!f || f.geometry.type !== "Polygon") return;
      const poly = f.geometry;
      onPolygonDrawnRef.current?.(poly, approxPolygonAreaM2(poly), drawTargetRef.current);
      onDrawProgressRef.current?.(null);
      try {
        draw.deleteAll();
      } catch {
        /* ignore */
      }
    };
    map.on("draw.create", onCreate);

    // While in draw_polygon mode, draw.render fires on every tick the
    // user moves the mouse or clicks a vertex. We compute live stats
    // off the in-progress feature so the page can show area/perimeter
    // /vertex-count without waiting for double-click finish.
    //
    // The in-progress polygon's outer ring is [v1, v2, ..., vn, mouse,
    // v1] — the trailing v1 closes the ring for rendering and the
    // pre-last vertex is the mouse cursor. We strip those two and
    // report only the clicked-vertex count. Perimeter follows the same
    // trimmed ring so the readout doesn't jitter as the mouse moves.
    const onRender = () => {
      if (!drawRef.current) {
        onDrawProgressRef.current?.(null);
        return;
      }
      const fc = drawRef.current.getAll();
      const f = fc.features[0];
      if (!f || f.geometry.type !== "Polygon") {
        onDrawProgressRef.current?.(null);
        return;
      }
      const fullRing = f.geometry.coordinates[0] ?? [];
      // Need at least mouse + closing-point to have a meaningful trim.
      if (fullRing.length < 2) {
        onDrawProgressRef.current?.({
          vertices: 0,
          areaM2: 0,
          perimeterM: 0,
          target: drawTargetRef.current,
        });
        return;
      }
      const clicked = fullRing.slice(0, -2);
      if (clicked.length < 1) {
        onDrawProgressRef.current?.({
          vertices: 0,
          areaM2: 0,
          perimeterM: 0,
          target: drawTargetRef.current,
        });
        return;
      }
      const trimmed: Polygon = { type: "Polygon", coordinates: [clicked] };
      const areaM2 = clicked.length >= 3 ? approxPolygonAreaM2(trimmed) : 0;
      const perimeterM = clicked.length >= 2 ? polygonPerimeterM(trimmed) : 0;
      onDrawProgressRef.current?.({
        vertices: clicked.length,
        areaM2,
        perimeterM,
        target: drawTargetRef.current,
      });
    };
    map.on("draw.render", onRender);

    return () => {
      map.off("draw.create", onCreate);
      map.off("draw.render", onRender);
      // Clear any leftover progress state so the page overlay disappears
      // immediately when draw mode is exited (vs. waiting for the next
      // render tick that never fires).
      onDrawProgressRef.current?.(null);
    };
  }, [drawEnabled, drawTarget]);

  // Reshape mode — load the selected block's polygon into mapbox-gl-draw
  // and put it into direct_select so the user can drag vertices.
  // Every draw.update emits the new polygon via onReshape; the page
  // commits on Save.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (!reshapeBlock) {
      if (drawRef.current && !drawEnabled) {
        try {
          map.removeControl(drawRef.current as unknown as maplibregl.IControl);
        } catch {
          /* ignore */
        }
        drawRef.current = null;
      }
      return;
    }

    const draw = new MapboxDraw({
      displayControlsDefault: false,
      controls: { trash: true },
    });
    drawRef.current = draw;
    map.addControl(draw as unknown as maplibregl.IControl, "top-left");

    const featureId = `reshape-${reshapeBlock.id}`;
    draw.add({
      type: "Feature",
      id: featureId,
      geometry: reshapeBlock.boundary,
      properties: {},
    });
    // The draw API queues mode changes until after the feature lands —
    // delaying to the next frame avoids a `feature not found` warning.
    requestAnimationFrame(() => {
      try {
        draw.changeMode("direct_select", { featureId });
      } catch {
        /* ignore */
      }
    });

    const onUpdate = () => {
      const all = draw.getAll();
      const f = all.features[0];
      if (!f || f.geometry.type !== "Polygon") return;
      onReshapeRef.current?.(f.geometry);
    };
    map.on("draw.update", onUpdate);

    return () => {
      map.off("draw.update", onUpdate);
      try {
        map.removeControl(draw as unknown as maplibregl.IControl);
      } catch {
        /* ignore */
      }
      drawRef.current = null;
    };
  }, [reshapeBlock, drawEnabled]);

  // Pivot draw mode — custom click-center + click-radius interaction.
  // First click places the center; mousemove draws a live circle
  // preview; second click confirms and emits {center, radius_m}.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (!drawEnabled || drawTarget !== "pivot") return;

    const PIVOT_SOURCE = "pivot-preview";
    const PIVOT_FILL = "pivot-preview-fill";
    const PIVOT_LINE = "pivot-preview-line";

    let center: [number, number] | null = null;

    const ensureSource = () => {
      if (map.getSource(PIVOT_SOURCE)) return;
      map.addSource(PIVOT_SOURCE, {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: PIVOT_FILL,
        type: "fill",
        source: PIVOT_SOURCE,
        paint: { "fill-color": "#0ea5e9", "fill-opacity": 0.18 },
      });
      map.addLayer({
        id: PIVOT_LINE,
        type: "line",
        source: PIVOT_SOURCE,
        paint: {
          "line-color": "#0369a1",
          "line-width": 2,
          "line-dasharray": [2, 2],
        },
      });
    };
    ensureSource();

    const setPreview = (c: [number, number] | null, radius_m: number) => {
      // See SOURCE_ID note above — tsc requires the cast, eslint thinks it's redundant.
      // eslint-disable-next-line @typescript-eslint/no-unnecessary-type-assertion
      const src = map.getSource(PIVOT_SOURCE) as GeoJSONSource | undefined;
      if (!src) return;
      if (!c || radius_m <= 0) {
        src.setData({ type: "FeatureCollection", features: [] });
        return;
      }
      src.setData({
        type: "FeatureCollection",
        features: [
          {
            type: "Feature",
            geometry: buildCircle(c[1], c[0], radius_m),
            properties: { radius_m },
          },
        ],
      });
    };

    const onClick = (ev: maplibregl.MapMouseEvent) => {
      const lonLat: [number, number] = [ev.lngLat.lng, ev.lngLat.lat];
      if (center == null) {
        center = lonLat;
        setPreview(center, 0);
      } else {
        const r = haversineMeters(center, lonLat);
        if (r > 5) {
          onPivotDrawnRef.current?.({
            center_lat: center[1],
            center_lon: center[0],
            radius_m: r,
          });
        }
        // Reset so the user can immediately draw another.
        center = null;
        setPreview(null, 0);
      }
    };
    const onMove = (ev: maplibregl.MapMouseEvent) => {
      if (center == null) return;
      const r = haversineMeters(center, [ev.lngLat.lng, ev.lngLat.lat]);
      setPreview(center, r);
    };
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === "Escape") {
        center = null;
        setPreview(null, 0);
      }
    };

    map.getCanvas().style.cursor = "crosshair";
    map.on("click", onClick);
    map.on("mousemove", onMove);
    window.addEventListener("keydown", onKey);

    return () => {
      map.off("click", onClick);
      map.off("mousemove", onMove);
      window.removeEventListener("keydown", onKey);
      map.getCanvas().style.cursor = "";
      // Tear down the preview layers so the next entry into pivot mode
      // starts clean.
      if (map.getLayer(PIVOT_LINE)) map.removeLayer(PIVOT_LINE);
      if (map.getLayer(PIVOT_FILL)) map.removeLayer(PIVOT_FILL);
      if (map.getSource(PIVOT_SOURCE)) map.removeSource(PIVOT_SOURCE);
    };
  }, [drawEnabled, drawTarget]);

  return (
    <div ref={containerRef} className="h-full w-full" role="application" aria-label="Farm map" />
  );
}

function computeBounds(
  fc: FeatureCollection<Polygon, UnitFeatureProps>,
  aoi: MultiPolygon | null,
): LngLatBoundsLike | null {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const f of fc.features) {
    for (const ring of f.geometry.coordinates) {
      for (const [x, y] of ring) {
        if (x < minX) minX = x;
        if (y < minY) minY = y;
        if (x > maxX) maxX = x;
        if (y > maxY) maxY = y;
      }
    }
  }
  if (aoi) {
    for (const poly of aoi.coordinates) {
      for (const ring of poly) {
        for (const [x, y] of ring) {
          if (x < minX) minX = x;
          if (y < minY) minY = y;
          if (x > maxX) maxX = x;
          if (y > maxY) maxY = y;
        }
      }
    }
  }
  if (!Number.isFinite(minX)) return null;
  return [
    [minX, minY],
    [maxX, maxY],
  ];
}

// approxPolygonAreaM2 + haversineMeters live in ./geo.ts so they can be
// unit-tested without loading maplibre. polygonPerimeterM is new there.

// Spherical-approximation circle for the on-map preview. Matches the
// backend's circle_polygon helper closely enough that the saved pivot
// covers the same footprint the user previewed.
function buildCircle(lat: number, lon: number, radius_m: number): Polygon {
  const R = 6_378_137;
  const vertices = 64;
  const coords: number[][] = [];
  const cosLat = Math.cos((lat * Math.PI) / 180);
  for (let i = 0; i < vertices; i++) {
    const theta = (2 * Math.PI * i) / vertices;
    const dx = radius_m * Math.cos(theta);
    const dy = radius_m * Math.sin(theta);
    const dlat = ((dy / R) * 180) / Math.PI;
    const dlon = ((dx / (R * cosLat)) * 180) / Math.PI;
    coords.push([lon + dlon, lat + dlat]);
  }
  coords.push(coords[0]);
  return { type: "Polygon", coordinates: [coords] };
}

// ringAreaM2 now lives in ./geo.ts.

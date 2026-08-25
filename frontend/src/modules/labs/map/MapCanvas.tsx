import { useEffect, useMemo, useRef } from "react";
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

import type { AnyIndexCode as ApiIndexCode } from "@/api/indices";
import { buildAlertBadgePoints } from "./alertBadges";
import { registerMarkerImages, SIGNAL_IMAGE_ID } from "./markerIcons";
import { gridRampExpression } from "./gridRamp";
import { HEALTH_FILL, HEALTH_FILL_OPACITY, HEALTH_STROKE } from "./health";
import { approxPolygonAreaM2, haversineMeters, polygonPerimeterM } from "./geo";
import type { FlagOverlayProps } from "./flagOverlay";
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
  // Field flags (tenant migration 0081). Same null = hide / FC = show contract
  // as the signal overlay above, so the layer toggle is one boolean.
  flagOverlay?: FeatureCollection<Point, FlagOverlayProps> | null;
  onFlagClick?: (flagId: string, point: { x: number; y: number }) => void;
  onSignalClick?: (observationId: string, point: { x: number; y: number }) => void;
  // Sub-block grid overlay (PR-grid). `null` hides; an FC shows.
  // Each feature must carry { cell_id: string, value: number | null }
  // in its properties; the heatmap color ramp reads `value`, the click
  // handler reads `cell_id`.
  gridCells?: FeatureCollection<Polygon, GridCellProps> | null;
  // Which index `gridCells[].value` holds. The heat ramp is per-index — the
  // classes are not interchangeable and two of them (ndwi, msi) read the
  // opposite way to the rest — so without this the cells would be coloured
  // against the wrong scale. `null` paints every cell as no-data grey rather
  // than guessing.
  gridIndexCode?: ApiIndexCode | null;
  onGridCellClick?: (cellId: string, point: { x: number; y: number }) => void;
  // G-2: cell ids to outline on the heatmap (the worst-N / alert-cited
  // cells), so a scout can see exactly where to go. Empty = none.
  highlightedCellIds?: string[];
  // The currently-open cell popup's cell — outlined with a bold blue
  // border so the operator can see which cell the popup refers to.
  // Distinct from the pink worst-N highlight. Null = none selected.
  selectedGridCellId?: string | null;
  // Auto-block candidate preview (Farm Console). `null` hides; an FC of
  // clipped candidate polygons paints them translucent over the map so the
  // operator sees exactly what auto-blocking will create before committing.
  autoBlockPreview?: FeatureCollection<Polygon> | null;
  // Bulk AOI-upload preview — polygons color-coded by reconcile status
  // ("new" | "reuse" | "replace" | "error") via a `status` feature property.
  bulkPreview?: FeatureCollection<Polygon, BulkPreviewProps> | null;
  // PR-R4b: when true, the block fill recolours by `risk_level` (worst
  // disease/pest pressure) instead of health. The features must carry
  // `risk_level`; blocks with "none" render unfilled so the base map shows.
  riskOverlay?: boolean;
  // Index pixels (Farm Console v2). One entry per block that has a raster for
  // the selected scene; each becomes its own MapLibre raster source pointed at
  // the tile server. The COGs are per block and per scene, so there is no one
  // farm-wide raster to point at — see the plan's note on mosaics.
  //
  // These draw ABOVE the satellite base and BELOW every vector layer, so block
  // outlines, cell lines, labels and badges all stay legible over them.
  pixelLayers?: PixelLayer[] | null;
  // Opacity for the pixel layers, 0..1.
  pixelOpacity?: number;
  // When false, sub-block cells keep their outlines but lose their fill. The
  // fill layer stays in the style at zero opacity rather than being hidden:
  // MapLibre will not hit-test a layer with `visibility: none`, and hiding it
  // would silently take the cell click — and with it the cell popup — away.
  gridFillVisible?: boolean;
  // Feature property holding a per-block fill colour (Farm Console v2 paints
  // the block's own index class). Null keeps the health palette, which is what
  // the live console still uses. Blocks without the property render unfilled
  // so the base map shows rather than defaulting to a colour that means
  // nothing.
  blockFillColorProperty?: string | null;
}

export interface PixelLayer {
  /** Stable per block: reused as the MapLibre source and layer id. */
  id: string;
  /** XYZ template with `{z}/{x}/{y}` intact. */
  tileUrl: string;
  /** Tile edge in pixels; must match what the URL requests. */
  tileSize?: number;
  /**
   * The block's extent as `[west, south, east, north]`.
   *
   * Not an optimisation. Each COG covers ONE block, and the tile server
   * answers 404 for anything outside it — so without a bound, every block's
   * source is asked for every tile in the viewport and all but one 404s.
   * That floods the console, wastes a request per block per tile, and leaves
   * MapLibre holding sources it considers errored.
   */
  bounds?: [number, number, number, number];
}

export interface GridCellProps {
  cell_id: string;
  // -1 is the no-data sentinel — see GRID_FILL_LAYER's fill-color
  // expression. Callers should encode null observations as -1 when
  // building the FeatureCollection.
  value: number;
}

export type BulkPreviewStatus = "new" | "reuse" | "replace" | "error";

export interface BulkPreviewProps {
  code: string;
  status: BulkPreviewStatus;
}

const SOURCE_ID = "units";
const FILL_LAYER = "units-fill";
const STROKE_LAYER = "units-stroke";
const SELECTED_LAYER = "units-selected";
const LABEL_LAYER = "units-label";
const LOGICAL_PIVOT_LAYER = "logical-pivot-ring";
const ALERT_BADGE_LAYER = "alert-badges";
// Alert badges need their own POINT source. A `circle` layer draws one
// circle per coordinate in the geometry it is bound to, so pointing it at
// the polygon `units` source rendered a badge on every vertex of every
// alerting block — a ring of red dots around the corners rather than one
// badge. `symbol` layers collapse a polygon to a single anchor, which is
// why the label layer next to it never had this problem.
const BADGE_SOURCE_ID = "alert-badge-points";
const AOI_SOURCE_ID = "farm-aoi";
const AOI_FILL_LAYER = "farm-aoi-fill";
const AOI_LINE_LAYER = "farm-aoi-line";
// CS-8: signal-observation overlay. One source + one circle layer
// per active overlay; the map page swaps the source data when the
// operator picks a different signal definition.
const FLAG_SOURCE_ID = "field-flag-overlay";
// One symbol layer each, where there used to be a circle plus a halo. A
// baked marker image carries its own white keyline, so the halo layer that
// used to buy contrast over satellite imagery has nothing left to do.
const FLAG_LAYER = "field-flag-symbol";
const SIGNAL_SOURCE_ID = "signal-overlay";
const SIGNAL_LAYER = "signal-overlay-symbol";
// Sub-block grid overlay layers.
const GRID_SOURCE_ID = "subblock-grid";
const GRID_FILL_LAYER = "subblock-grid-fill";
const GRID_LINE_LAYER = "subblock-grid-line";
const GRID_HIGHLIGHT_LAYER = "subblock-grid-highlight";
const GRID_SELECTED_LAYER = "subblock-grid-selected";
// Auto-block candidate preview (Farm Console).
const PREVIEW_SOURCE_ID = "autoblock-preview";
const PREVIEW_FILL_LAYER = "autoblock-preview-fill";
const PREVIEW_LINE_LAYER = "autoblock-preview-line";
// Bulk AOI-upload preview (Farm Console) — color-coded by reconcile status.
const BULK_SOURCE_ID = "bulk-aoi-preview";
const BULK_FILL_LAYER = "bulk-aoi-preview-fill";
const BULK_LINE_LAYER = "bulk-aoi-preview-line";
// status -> fill/line color. Matches the review-table + legend palette
// (ap-good / ap-muted / ap-warn / ap-crit).
const BULK_STATUS_COLOR: Record<BulkPreviewStatus, string> = {
  new: "#4f8e4a", // ap-good
  reuse: "#6c7268", // ap-muted (a no-op)
  replace: "#c98a18", // ap-warn
  error: "#b24430", // ap-crit
};
const BULK_COLOR_EXPR: ExpressionSpecification = [
  "match",
  ["get", "status"],
  "new",
  BULK_STATUS_COLOR.new,
  "reuse",
  BULK_STATUS_COLOR.reuse,
  "replace",
  BULK_STATUS_COLOR.replace,
  "error",
  BULK_STATUS_COLOR.error,
  "#6b7280", // gray-500 fallback
];

// Index-pixel raster layers (Farm Console v2). Prefixed so the sync effect can
// find its own layers in the style without keeping a parallel list that could
// drift from what is actually mounted.
const PIXEL_LAYER_PREFIX = "index-pixels-";
function pixelLayerId(blockId: string): string {
  return `${PIXEL_LAYER_PREFIX}${blockId}`;
}

/**
 * The first non-raster layer in the style — the insertion point that keeps
 * pixels under every vector layer. Returns null when the style is still all
 * raster, in which case appending on top is correct anyway.
 */
function firstVectorLayerId(map: MlMap): string | null {
  for (const layer of map.getStyle().layers ?? []) {
    if (layer.type !== "raster" && layer.type !== "background") return layer.id;
  }
  return null;
}

/**
 * Opacity for a block filled by its own index class. Higher than the health
 * fill's 0.5–0.7: a flat class colour has to read as the same colour the
 * pixels use, and a washed-out version of it reads as a different class.
 */
const CLASS_FILL_OPACITY = 0.8;

const AOI_STROKE = "#0ea5e9"; // cyan-500 — distinct from block strokes
const AOI_FILL = "#0ea5e9";
// PR-R4b risk-overlay fill. Mirrors the health palette (green/amber/red) so
// the map reads consistently; "none" is transparent so unscored blocks fall
// back to the bare satellite base while the overlay is on.
const RISK_FILL: Record<string, string> = {
  low: "#97C459",
  moderate: "#EF9F27",
  high: "#E24B4A",
  none: "#000000",
};
const RISK_FILL_OPACITY: Record<string, number> = {
  low: 0.55,
  moderate: 0.6,
  high: 0.65,
  none: 0,
};

// Esri publishes World Imagery as a 256px pyramid. MapLibre picks which
// pyramid level to fetch from the DECLARED tileSize — coveringZoomLevel is
// `floor(zoom + log2(512 / tileSize))` — so declaring 128 makes it fetch one
// level deeper for the same screen area. On a hi-DPI display that lands one
// source pixel on one *device* pixel instead of stretching it over four, which
// is much of the "why is this blurrier than Google Maps" gap at the zooms
// people actually work at (whole-farm and multi-block views).
//
// It costs 4x the tile requests and buys nothing on a 1x display, so only opt
// in where it pays. Read at map construction rather than module load so a
// window opened on an external retina screen still gets it right.
function satelliteTileSize(): number {
  const dpr = typeof window === "undefined" ? 1 : window.devicePixelRatio || 1;
  return dpr >= 1.5 ? 128 : 256;
}

// Esri genuinely has no imagery above pyramid level 19 over Egypt — verified
// against the service's own /tilemap endpoint, which reports z19 over the Nile
// Delta and Cairo and only z18 around Suez/Ismailia. Raising this buys blank
// tiles, not detail; getting past ~0.26 m/px needs a different provider.
const SATELLITE_MAXZOOM = 19;

function buildStyle(): StyleSpecification {
  return {
    version: 8,
    glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
    sources: {
      satellite: {
        type: "raster",
        tiles: [
          "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        ],
        tileSize: satelliteTileSize(),
        attribution:
          "Tiles © Esri — Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community",
        maxzoom: SATELLITE_MAXZOOM,
      },
    },
    layers: [
      { id: "background", type: "background", paint: { "background-color": "#b5ad8e" } },
      {
        id: "satellite",
        type: "raster",
        source: "satellite",
        paint: { "raster-opacity": 1, "raster-resampling": "linear" },
      },
    ],
  };
}

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
  flagOverlay = null,
  onFlagClick,
  onSignalClick,
  gridCells = null,
  gridIndexCode = null,
  onGridCellClick,
  highlightedCellIds = [],
  selectedGridCellId = null,
  autoBlockPreview = null,
  bulkPreview = null,
  riskOverlay = false,
  pixelLayers = null,
  pixelOpacity = 0.85,
  gridFillVisible = true,
  blockFillColorProperty = null,
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
  const onFlagClickRef = useRef(onFlagClick);
  onFlagClickRef.current = onFlagClick;
  // Read inside the mount-only map-creation effect, which would otherwise
  // close over the index selected on first render forever.
  const gridIndexCodeRef = useRef(gridIndexCode);
  gridIndexCodeRef.current = gridIndexCode;
  const onGridCellClickRef = useRef(onGridCellClick);
  onGridCellClickRef.current = onGridCellClick;
  // Tracks the farm we last fit-bounds to, so data refetches don't re-zoom.
  const lastFitKeyRef = useRef<string | null>(null);
  // The mount effect has `[]` deps, so it reads the FIRST render's geometry
  // through this ref (same pattern as the callback refs above). Callers gate
  // the canvas on their data query, so the farm is already known at mount —
  // seeding the constructor with its bounds is what removes the zoom flash.
  const initialViewRef = useRef({ geojson, farmBoundary, fitBoundsKey });

  // One badge anchor per alerting block — see alertBadges.ts for why the
  // badge layer cannot read the polygon source directly.
  const badgePoints = useMemo(() => buildAlertBadgePoints(geojson), [geojson]);

  // Initial mount.
  useEffect(() => {
    if (!containerRef.current) return;
    // Framing the map at construction, instead of flying to the farm once the
    // data effect runs, is what stops the "open Farm Management → watch it
    // zoom in" flash: otherwise the first paint is the default view below.
    // maplibre applies `bounds` after center/zoom, with duration forced to 0.
    const initial = initialViewRef.current;
    const initialBounds = computeBounds(initial.geojson, initial.farmBoundary ?? null);
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: buildStyle(),
      center: [31.0, 30.5],
      zoom: 14,
      bounds: initialBounds ?? undefined,
      fitBoundsOptions: { padding: 40 },
      attributionControl: { compact: true },
    });
    // Already framed on this farm — record it so the data effect below does
    // not animate a second fit over an already-correct view.
    if (initialBounds) lastFitKeyRef.current = initial.fitBoundsKey;
    mapRef.current = map;
    map.dragRotate.disable();
    map.touchZoomRotate.disableRotation();
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-left");

    // maplibre's trackResize only listens to WINDOW resizes, so when a side
    // panel (the inspector) opens/closes and resizes this container — not the
    // window — the canvas keeps its old size and the map appears to jump/zoom.
    // Observe the container and resize the map explicitly.
    const resizeObserver = new ResizeObserver(() => {
      mapRef.current?.resize();
    });
    if (containerRef.current) resizeObserver.observe(containerRef.current);

    map.on("load", () => {
      // Marker artwork first: MapLibre resolves `icon-image` at draw time,
      // and a symbol whose image is missing renders as nothing at all with
      // no error, so registering after the layers would leave the map blank
      // until the next repaint that happened to follow registration.
      registerMarkerImages(map);

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

      // Alert markers. A severity-coloured chip carrying the glyph for the
      // worst open alert's action_type, with the number of open alerts
      // fitted into it. Replaces a plain circle that could say neither what
      // the alert was about nor how many there were.
      //
      // Bound to the derived point source, never to `units`: see
      // BADGE_SOURCE_ID for what a circle layer did to a polygon source.
      map.addSource(BADGE_SOURCE_ID, {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: ALERT_BADGE_LAYER,
        type: "symbol",
        source: BADGE_SOURCE_ID,
        layout: {
          // The id is resolved in alertBadges.ts rather than by a `match`
          // here, so the ids the layer asks for and the ids registered with
          // the map come from the same function.
          "icon-image": ["get", "marker_icon"],
          // Grows the chip around the count. The image's stretch region sits
          // to the right of the glyph, so a three-digit count widens the
          // chip without distorting the droplet.
          "icon-text-fit": "both",
          "icon-text-fit-padding": [2, 6, 2, 2],
          "text-field": ["get", "marker_count"],
          "text-size": 12,
          // An alert is the one thing on this map that must never be hidden
          // by label collision. If two blocks are small and adjacent, seeing
          // both chips overlap is better than one of them vanishing.
          "icon-allow-overlap": true,
          "icon-ignore-placement": true,
          "text-allow-overlap": true,
          "text-ignore-placement": true,
          // Up and to the right of the block's anchor point, so the chip
          // does not bury the block's name label. Ems, because the offset
          // moves the text and the fitted icon follows it.
          "text-offset": [1.1, -1.1],
        },
        paint: {
          "text-color": "#ffffff",
        },
      });

      // CS-8: signal observations. A hollow diamond in one neutral colour —
      // a reading somebody took, not a problem somebody found, so it is the
      // quietest of the three marker shapes.
      map.addSource(SIGNAL_SOURCE_ID, {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: SIGNAL_LAYER,
        type: "symbol",
        source: SIGNAL_SOURCE_ID,
        layout: {
          "icon-image": SIGNAL_IMAGE_ID,
          "icon-allow-overlap": true,
          "icon-ignore-placement": true,
        },
      });

      map.on("mousemove", FILL_LAYER, () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", FILL_LAYER, () => {
        map.getCanvas().style.cursor = "";
      });
      // Field flags — a pennant, planted on the spot the scout marked.
      //
      // Colour is the severity THEY chose (`field_flags.severity`, tenant
      // migration 0081), so the pin says how bad they thought it was, not
      // how bad anything downstream decided it was. Open flags are filled;
      // a closed one is a hollow outline in the same colour, because a
      // closed pin stays on the map until its `pin_until` runs out and the
      // layer has to say which work is finished without changing what the
      // pin is about.
      map.addSource(FLAG_SOURCE_ID, {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: FLAG_LAYER,
        type: "symbol",
        source: FLAG_SOURCE_ID,
        layout: {
          "icon-image": ["get", "marker_icon"],
          // The image puts the foot of the pole on its bottom centre, so a
          // bottom anchor plants the pole on the coordinate itself. A centre
          // anchor would float the pin half its height north of the spot.
          "icon-anchor": "bottom",
          "icon-allow-overlap": true,
          "icon-ignore-placement": true,
        },
      });
      map.on("mousemove", FLAG_LAYER, () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", FLAG_LAYER, () => {
        map.getCanvas().style.cursor = "";
      });
      map.on("click", FLAG_LAYER, (ev) => {
        const f = ev.features?.[0];
        if (!f) return;
        const props = f.properties as { flag_id?: string };
        if (props.flag_id) {
          onFlagClickRef.current?.(props.flag_id, { x: ev.point.x, y: ev.point.y });
        }
      });

      map.on("mousemove", SIGNAL_LAYER, () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", SIGNAL_LAYER, () => {
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
          //
          // The stops live in gridRamp.ts so the index legend can draw
          // swatches from the same table — a legend that disagrees with the
          // pixels under it reads as a bug.
          //
          // Seeded with whatever index is selected at mount; the effect below
          // keeps it in step as the operator switches.
          "fill-color": gridRampExpression(gridIndexCodeRef.current),
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
      // Selected-cell outline — a bold blue border over the cell whose
      // popup is currently open, so the operator can see which cell the
      // popup describes. Deliberately distinct from the pink worst-N
      // highlight above. Starts matching nothing; the selectedGridCellId
      // effect swaps the filter.
      map.addLayer({
        id: GRID_SELECTED_LAYER,
        type: "line",
        source: GRID_SOURCE_ID,
        filter: ["==", ["get", "cell_id"], ""],
        paint: {
          "line-color": "#1d4ed8", // blue-700 — distinct from pink worst-N
          "line-width": 3,
          "line-opacity": 1,
        },
      });
      // Auto-block candidate preview — translucent cyan fills with a dashed
      // outline, painted over the satellite base so the operator previews
      // exactly the clipped candidates auto-blocking will create. Starts
      // empty; the autoBlockPreview effect swaps the data + visibility.
      map.addSource(PREVIEW_SOURCE_ID, {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: PREVIEW_FILL_LAYER,
        type: "fill",
        source: PREVIEW_SOURCE_ID,
        paint: { "fill-color": "#22d3ee", "fill-opacity": 0.3 },
      });
      map.addLayer({
        id: PREVIEW_LINE_LAYER,
        type: "line",
        source: PREVIEW_SOURCE_ID,
        paint: { "line-color": "#0891b2", "line-width": 1.2, "line-dasharray": [2, 1] },
      });
      // Bulk AOI-upload preview — translucent fills color-coded by reconcile
      // status (new/reuse/replace/error) so the operator sees, before commit,
      // which uploaded boundaries create, match, or replace existing blocks.
      // Starts empty; the bulkPreview effect swaps the data + visibility.
      map.addSource(BULK_SOURCE_ID, {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: BULK_FILL_LAYER,
        type: "fill",
        source: BULK_SOURCE_ID,
        paint: { "fill-color": BULK_COLOR_EXPR, "fill-opacity": 0.32 },
      });
      map.addLayer({
        id: BULK_LINE_LAYER,
        type: "line",
        source: BULK_SOURCE_ID,
        paint: { "line-color": BULK_COLOR_EXPR, "line-width": 1.6 },
      });

      // Keep block name labels above the grid heatmap so they stay legible
      // (and clickable as the block-open affordance) when the overlay is on.
      // Raise the signal dots above the heatmap too so they stay visible +
      // clickable. Order ends up grid < signals < labels — labels still win
      // a click (the GRID handler guards on them), the signal dots win over
      // grid cells (the GRID handler also guards on them).
      if (map.getLayer(SIGNAL_LAYER)) map.moveLayer(SIGNAL_LAYER);
      if (map.getLayer(FLAG_LAYER)) map.moveLayer(FLAG_LAYER);
      map.moveLayer(LABEL_LAYER);
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
        // Block labels sit above the heatmap and are the block-open
        // affordance; if the click also landed on a label, let the label
        // handler win so a label opens the block, not a cell.
        if (map.queryRenderedFeatures(ev.point, { layers: [LABEL_LAYER] }).length > 0) {
          return;
        }
        // Observation dots sit above the heatmap and have their own click
        // handler; if the click also landed on a dot, let the signal
        // handler win so a dot opens the observation, not a cell.
        if (map.queryRenderedFeatures(ev.point, { layers: [SIGNAL_LAYER] }).length > 0) {
          return;
        }
        const f = ev.features?.[0];
        if (!f) return;
        const props = f.properties as { cell_id?: string };
        if (props.cell_id)
          onGridCellClickRef.current?.(props.cell_id, { x: ev.point.x, y: ev.point.y });
      });
      // Clicking a block's name label selects the block. With the grid
      // overlay on, the heatmap covers the polygon fill, so the label is
      // the way to open the block drawer.
      map.on("click", LABEL_LAYER, (ev) => {
        const f = ev.features?.[0];
        if (!f) return;
        const props = f.properties as Pick<UnitFeatureProps, "id">;
        onSelectRef.current(props.id);
      });
      map.on("mousemove", LABEL_LAYER, () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", LABEL_LAYER, () => {
        map.getCanvas().style.cursor = "";
      });
      map.on("click", SIGNAL_LAYER, (ev) => {
        const f = ev.features?.[0];
        if (!f) return;
        const props = f.properties as { observation_id?: string };
        if (props.observation_id) {
          onSignalClickRef.current?.(props.observation_id, { x: ev.point.x, y: ev.point.y });
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
      resizeObserver.disconnect();
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // Push GeoJSON data whenever it changes, but fit bounds ONLY when the farm
  // (fitBoundsKey) changes — not on every 60s data refetch, which would
  // re-zoom the map out from under the user (the flicker bug). lastFitKeyRef
  // records the farm we last fitted to; null means "not yet fitted".
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
      // eslint-disable-next-line @typescript-eslint/no-unnecessary-type-assertion
      const badgeSrc = map.getSource(BADGE_SOURCE_ID) as GeoJSONSource | undefined;
      if (badgeSrc) badgeSrc.setData(badgePoints);
      if (lastFitKeyRef.current !== fitBoundsKey) {
        const bounds = computeBounds(geojson, farmBoundary ?? null);
        if (bounds) {
          // Animate only when moving BETWEEN farms — the motion tells the user
          // the map followed their switch. A first fit here means the mount
          // had no geometry yet, so animating it would just be the flash.
          map.fitBounds(bounds, {
            padding: 40,
            duration: lastFitKeyRef.current === null ? 0 : 600,
          });
          lastFitKeyRef.current = fitBoundsKey;
        }
      }
    };
    if (map.isStyleLoaded()) apply();
    else map.once("load", apply);
  }, [geojson, fitBoundsKey, farmBoundary]);

  // What colours a block polygon, in ONE place.
  //
  // Three effects used to write these two paint properties — the risk toggle,
  // the opacity slider, and the initial layer definition — and whichever ran
  // last won. That was survivable while there were two modes; it is not with
  // three. Moving the slider while the risk overlay was on visibly reverted
  // the fill to the health palette, which is the bug this consolidation also
  // fixes.
  //
  // Precedence: an explicit per-feature colour (v2's index class) beats the
  // risk overlay, which beats health.
  const blockFillPaint = (): {
    color: ExpressionSpecification | string;
    opacity: ExpressionSpecification | number;
  } => {
    const mul = Math.max(0, Math.min(1, blockFillOpacity));
    if (blockFillColorProperty) {
      const prop = blockFillColorProperty;
      return {
        color: [
          "case",
          ["has", prop],
          ["get", prop],
          "rgba(0,0,0,0)",
        ] as unknown as ExpressionSpecification,
        // A block with no reading for this scene stays unfilled so the
        // satellite base shows through — a colour there would have to mean
        // something, and "we don't know" is not on the ramp.
        opacity: [
          "case",
          ["!", ["has", prop]],
          0,
          ["==", ["get", "is_future"], true],
          0.25 * mul,
          CLASS_FILL_OPACITY * mul,
        ] as unknown as ExpressionSpecification,
      };
    }
    if (riskOverlay) {
      return {
        color: healthMatch("risk_level", RISK_FILL, RISK_FILL.none),
        opacity: healthMatch("risk_level", RISK_FILL_OPACITY, RISK_FILL_OPACITY.none),
      };
    }
    return {
      color: healthMatch("health", HEALTH_FILL, HEALTH_FILL.unknown),
      opacity: [
        "case",
        ["==", ["get", "is_future"], true],
        0.25 * mul,
        ["*", mul, healthMatch("health", HEALTH_FILL_OPACITY, HEALTH_FILL_OPACITY.unknown)],
      ] as unknown as ExpressionSpecification,
    };
  };

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = () => {
      if (!map.getLayer(FILL_LAYER)) return;
      const paint = blockFillPaint();
      map.setPaintProperty(FILL_LAYER, "fill-color", paint.color);
      map.setPaintProperty(FILL_LAYER, "fill-opacity", paint.opacity);
    };
    if (map.isStyleLoaded()) apply();
    else map.once("load", apply);
    // blockFillPaint is rebuilt every render by design; these are the inputs
    // it actually reads.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [riskOverlay, blockFillColorProperty, blockFillOpacity]);

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
      for (const layerId of [SIGNAL_LAYER]) {
        if (!map.getLayer(layerId)) continue;
        map.setLayoutProperty(layerId, "visibility", visible ? "visible" : "none");
      }
    };
    if (map.isStyleLoaded()) apply();
    else map.once("load", apply);
  }, [signalOverlay]);

  // Field flags. Same contract as the signal overlay: null hides the layer,
  // an FC shows it.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = () => {
      // eslint-disable-next-line @typescript-eslint/no-unnecessary-type-assertion
      const src = map.getSource(FLAG_SOURCE_ID) as GeoJSONSource | undefined;
      if (!src) return;
      const visible = flagOverlay !== null;
      src.setData(flagOverlay ?? { type: "FeatureCollection", features: [] });
      for (const layerId of [FLAG_LAYER]) {
        if (!map.getLayer(layerId)) continue;
        map.setLayoutProperty(layerId, "visibility", visible ? "visible" : "none");
      }
    };
    if (map.isStyleLoaded()) apply();
    else map.once("load", apply);
  }, [flagOverlay]);

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
      for (const layerId of [
        GRID_FILL_LAYER,
        GRID_LINE_LAYER,
        GRID_HIGHLIGHT_LAYER,
        GRID_SELECTED_LAYER,
      ]) {
        if (!map.getLayer(layerId)) continue;
        map.setLayoutProperty(layerId, "visibility", visible ? "visible" : "none");
      }
    };
    if (map.isStyleLoaded()) apply();
    else map.once("load", apply);
  }, [gridCells]);

  // Auto-block candidate preview — same null = hide / FC = show pattern.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = () => {
      // eslint-disable-next-line @typescript-eslint/no-unnecessary-type-assertion
      const src = map.getSource(PREVIEW_SOURCE_ID) as GeoJSONSource | undefined;
      if (!src) return;
      const visible = autoBlockPreview != null;
      src.setData(autoBlockPreview ?? { type: "FeatureCollection", features: [] });
      for (const layerId of [PREVIEW_FILL_LAYER, PREVIEW_LINE_LAYER]) {
        if (!map.getLayer(layerId)) continue;
        map.setLayoutProperty(layerId, "visibility", visible ? "visible" : "none");
      }
    };
    if (map.isStyleLoaded()) apply();
    else map.once("load", apply);
  }, [autoBlockPreview]);

  // Bulk AOI-upload preview — same null = hide / FC = show pattern.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = () => {
      // eslint-disable-next-line @typescript-eslint/no-unnecessary-type-assertion
      const src = map.getSource(BULK_SOURCE_ID) as GeoJSONSource | undefined;
      if (!src) return;
      const visible = bulkPreview != null;
      src.setData(bulkPreview ?? { type: "FeatureCollection", features: [] });
      for (const layerId of [BULK_FILL_LAYER, BULK_LINE_LAYER]) {
        if (!map.getLayer(layerId)) continue;
        map.setLayoutProperty(layerId, "visibility", visible ? "visible" : "none");
      }
    };
    if (map.isStyleLoaded()) apply();
    else map.once("load", apply);
  }, [bulkPreview]);

  // G-2: outline the cited cells (worst-N / alert) via a filter swap on
  // the highlight layer — same lightweight pattern as the block selection
  // highlight. An empty list matches nothing.
  //
  // Gate on the layer EXISTING, not on `isStyleLoaded()`: `setFilter` works
  // the moment the layer is present, even while the style transiently
  // reports not-loaded mid-`setData`. The worst-cells query resolves around
  // the same time as the grid-cells data, so an `isStyleLoaded()` guard
  // here would fall through to `once("load")` — which never fires again
  // post-load — and the highlight would be silently dropped.
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
    if (map.getLayer(GRID_HIGHLIGHT_LAYER)) apply();
    else map.once("load", apply);
  }, [highlightedCellIds]);

  // Outline the cell whose popup is open via a filter swap on the selected
  // layer — same gate-on-layer-existing rationale as the highlight effect
  // above. Empty/null selection matches nothing.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = () => {
      if (!map.getLayer(GRID_SELECTED_LAYER)) return;
      map.setFilter(GRID_SELECTED_LAYER, ["==", ["get", "cell_id"], selectedGridCellId ?? ""]);
    };
    if (map.getLayer(GRID_SELECTED_LAYER)) apply();
    else map.once("load", apply);
  }, [selectedGridCellId]);

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

      // Block fill opacity is NOT set here any more — the slider is one of
      // three inputs to the fill paint, and applying it separately is what let
      // the last effect to run overwrite the other two. See blockFillPaint.
    };
    if (map.isStyleLoaded()) apply();
    else map.once("load", apply);
  }, [showAoi, showBlocks, showBlockBorders, showBlockLabels, borderOpacity]);

  // Index pixels: one raster source + layer per block that has a raster for
  // the selected scene.
  //
  // Sources are added and removed by id rather than rebuilt wholesale, so
  // scrubbing the timeline does not tear down and re-add every block's tiles
  // — and a block whose tiles are already loaded keeps them on screen while
  // its neighbours load. Each layer is inserted BENEATH the first vector
  // layer, which keeps block outlines, cell lines and labels above the pixels
  // without having to re-sort the whole style.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = () => {
      const wanted = new Map((pixelLayers ?? []).map((l) => [pixelLayerId(l.id), l]));
      // Drop the ones no longer wanted (different scene, index, or block set).
      for (const layer of map.getStyle().layers ?? []) {
        if (!layer.id.startsWith(PIXEL_LAYER_PREFIX) || wanted.has(layer.id)) continue;
        if (map.getLayer(layer.id)) map.removeLayer(layer.id);
        if (map.getSource(layer.id)) map.removeSource(layer.id);
      }
      for (const [id, layer] of wanted) {
        const existing = map.getSource(id);
        if (existing) {
          // Same block, new URL (index or scene changed): swap the tiles in
          // place. `setTiles` is the only way to repoint a raster source
          // without dropping the layer and flashing the base map.
          const raster = existing as maplibregl.RasterTileSource;
          if (raster.tiles?.[0] !== layer.tileUrl) raster.setTiles([layer.tileUrl]);
        } else {
          map.addSource(id, {
            type: "raster",
            tiles: [layer.tileUrl],
            // Must match the size the URL asks the server for — TiTiler's
            // `scale`, times 256. Declaring 512 does two things: it fetches
            // one pyramid level LOWER, so each tile covers twice the ground
            // per axis, and it draws whatever comes back across a 512 CSS
            // footprint. Handed a 256 image for that, MapLibre stretches it
            // with the `nearest` resampling below, and every raster pixel is
            // drawn at four times its area with hard edges — the pixel grid
            // `reproject=bilinear` exists to remove. See `SCALE` in
            // pixelTiles.ts for how the two got out of step.
            tileSize: layer.tileSize ?? 256,
            // The COG covers one block; asking beyond its native resolution
            // buys blank tiles, so let MapLibre overzoom the last real level.
            maxzoom: 20,
            ...(layer.bounds ? { bounds: layer.bounds } : {}),
          });
          map.addLayer(
            {
              id,
              type: "raster",
              source: id,
              paint: { "raster-opacity": pixelOpacity, "raster-resampling": "nearest" },
            },
            firstVectorLayerId(map) ?? undefined,
          );
        }
        if (map.getLayer(id)) map.setPaintProperty(id, "raster-opacity", pixelOpacity);
      }
    };
    // `idle`, NOT `load`. These layers arrive well after the first paint — the
    // statistics call decides which blocks have a readable raster — and by then
    // `load` has already fired for good. Deferring to it means the pixels are
    // never added at all, which is the same trap the grid-highlight effect
    // below documents. `idle` fires every time the map goes quiet, so a style
    // that is mid-update when this runs still gets its layers.
    if (map.isStyleLoaded()) apply();
    else map.once("idle", apply);
  }, [pixelLayers, pixelOpacity]);

  // Cells as lines: drop the fill without dropping the click. See the prop's
  // note — `visibility: none` would also remove the layer from hit-testing,
  // taking the cell popup with it.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = () => {
      if (!map.getLayer(GRID_FILL_LAYER)) return;
      map.setPaintProperty(GRID_FILL_LAYER, "fill-opacity", gridFillVisible ? 0.6 : 0);
    };
    if (map.getLayer(GRID_FILL_LAYER)) apply();
    else map.once("load", apply);
  }, [gridFillVisible]);

  // Repaint the heatmap when the operator switches index. The layer is created
  // once on map load, so without this the cells would keep the ramp of
  // whichever index happened to be selected first — and since the class tables
  // are not interchangeable, that silently misreads every cell rather than
  // failing visibly.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = () => {
      if (!map.getLayer(GRID_FILL_LAYER)) return;
      map.setPaintProperty(GRID_FILL_LAYER, "fill-color", gridRampExpression(gridIndexCode));
    };
    if (map.getLayer(GRID_FILL_LAYER)) apply();
    else map.once("load", apply);
  }, [gridIndexCode]);

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

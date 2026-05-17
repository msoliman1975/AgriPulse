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
import type { UnitFeatureProps } from "./types";
import type { FeatureCollection, MultiPolygon, Polygon } from "geojson";

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

interface Props {
  geojson: FeatureCollection<Polygon, UnitFeatureProps>;
  farmBoundary?: MultiPolygon | null;
  selectedId: string | null;
  onSelect: (id: string) => void;
  fitBoundsKey: string; // pass farm ID; bumping it refits
  drawEnabled?: boolean;
  drawTarget?: DrawTarget;
  onPolygonDrawn?: (polygon: Polygon, areaM2: number, target: DrawTarget) => void;
  onPivotDrawn?: (result: PivotDrawResult) => void;
  // When set, MapCanvas enters direct-select mode against the supplied
  // polygon so the user can drag vertices. Every edit emits the new
  // polygon via onReshape; the page commits on Save.
  reshapeBlock?: { id: string; boundary: Polygon } | null;
  onReshape?: (polygon: Polygon) => void;
  // Visibility / styling toggles from the page toolbar.
  showAoi?: boolean;
  showBlockBorders?: boolean;
  showBlockLabels?: boolean;
  // 0..1 multiplier applied to AOI line opacity and block stroke opacity.
  borderOpacity?: number;
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

const AOI_STROKE = "#0ea5e9"; // cyan-500 — distinct from block strokes
const AOI_FILL = "#0ea5e9";

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
  onPivotDrawn,
  reshapeBlock = null,
  onReshape,
  showAoi = true,
  showBlockBorders = true,
  showBlockLabels = true,
  borderOpacity = 0.9,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MlMap | null>(null);
  const drawRef = useRef<MapboxDraw | null>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const onPolygonDrawnRef = useRef(onPolygonDrawn);
  onPolygonDrawnRef.current = onPolygonDrawn;
  const drawTargetRef = useRef(drawTarget);
  drawTargetRef.current = drawTarget;
  const onPivotDrawnRef = useRef(onPivotDrawn);
  onPivotDrawnRef.current = onPivotDrawn;
  const onReshapeRef = useRef(onReshape);
  onReshapeRef.current = onReshape;

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

      map.on("mousemove", FILL_LAYER, () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", FILL_LAYER, () => {
        map.getCanvas().style.cursor = "";
      });

      map.on("click", FILL_LAYER, (ev) => {
        const f = ev.features?.[0];
        if (!f) return;
        const props = f.properties as Pick<UnitFeatureProps, "id">;
        onSelectRef.current(props.id);
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
      setVis(STROKE_LAYER, !!showBlockBorders);
      setVis(STROKE_LAYER + "-future", !!showBlockBorders);
      setVis(LOGICAL_PIVOT_LAYER, !!showBlockBorders);
      setVis(LABEL_LAYER, !!showBlockLabels);

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
    };
    if (map.isStyleLoaded()) apply();
    else map.once("load", apply);
  }, [showAoi, showBlockBorders, showBlockLabels, borderOpacity]);

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
      try {
        draw.deleteAll();
      } catch {
        /* ignore */
      }
    };
    map.on("draw.create", onCreate);

    return () => {
      map.off("draw.create", onCreate);
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

// Spherical-excess approximation, accurate enough for human-scale block
// previews (sub-1% error up to ~50 km). Returns area in square metres.
function approxPolygonAreaM2(poly: Polygon): number {
  const R = 6_378_137; // WGS-84 equatorial radius
  let total = 0;
  for (let i = 0; i < poly.coordinates.length; i++) {
    const ring = poly.coordinates[i];
    const a = ringAreaM2(ring, R);
    // First ring is exterior, subsequent rings are holes.
    total += i === 0 ? Math.abs(a) : -Math.abs(a);
  }
  return total;
}

function haversineMeters(a: [number, number], b: [number, number]): number {
  const R = 6_378_137;
  const [lon1, lat1] = a;
  const [lon2, lat2] = b;
  const phi1 = (lat1 * Math.PI) / 180;
  const phi2 = (lat2 * Math.PI) / 180;
  const dphi = ((lat2 - lat1) * Math.PI) / 180;
  const dl = ((lon2 - lon1) * Math.PI) / 180;
  const x = Math.sin(dphi / 2) ** 2 + Math.cos(phi1) * Math.cos(phi2) * Math.sin(dl / 2) ** 2;
  return 2 * R * Math.atan2(Math.sqrt(x), Math.sqrt(1 - x));
}

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

function ringAreaM2(ring: number[][], R: number): number {
  if (ring.length < 3) return 0;
  let total = 0;
  for (let i = 0; i < ring.length; i++) {
    const [lon1, lat1] = ring[i];
    const [lon2, lat2] = ring[(i + 1) % ring.length];
    total +=
      (((lon2 - lon1) * Math.PI) / 180) *
      (2 + Math.sin((lat1 * Math.PI) / 180) + Math.sin((lat2 * Math.PI) / 180));
  }
  return (total * R * R) / 2;
}

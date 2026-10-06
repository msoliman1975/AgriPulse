import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import MapboxDraw from "@mapbox/mapbox-gl-draw";
import type { Feature, FeatureCollection, Polygon } from "geojson";

import { bboxOfGeometry, centerOfBbox } from "@/lib/geometry";

const DEFAULT_CENTER: [number, number] = [31.2357, 30.0444]; // Cairo
const DEFAULT_ZOOM = 5;

const RASTER_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution: "© OpenStreetMap contributors",
    },
  },
  layers: [{ id: "osm", type: "raster", source: "osm" }],
};

/**
 * Read-only shapes drawn under the editable polygon, for orientation.
 * `kind: "frame"` is the outline the drawing must stay inside (a block when
 * drawing a holding); `kind: "neighbour"` is a shape it must not overlap.
 */
export interface MapDrawReference {
  geometry: Polygon;
  kind: "frame" | "neighbour";
}

interface Props {
  initial?: Polygon | null;
  mode?: "draw_polygon" | "simple_select";
  onChange?: (polygon: Polygon | null) => void;
  references?: MapDrawReference[];
  className?: string;
}

/**
 * MapLibre + mapbox-gl-draw polygon editor. mapbox-gl-draw is the
 * established library here even though we use maplibre — both speak the
 * same Mapbox GL JS API surface for layers/sources/events. The cast on
 * `addControl` paves over the typings mismatch.
 */
export function MapDraw({
  initial,
  mode = "draw_polygon",
  onChange,
  references,
  className,
}: Props): JSX.Element {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const drawRef = useRef<MapboxDraw | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const focus = initial ?? references?.[0]?.geometry ?? null;
    const center = focus ? centerOfBbox(focus) : DEFAULT_CENTER;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: RASTER_STYLE,
      center,
      zoom: initial ? 13 : focus ? 15 : DEFAULT_ZOOM,
    });
    mapRef.current = map;

    const draw = new MapboxDraw({
      displayControlsDefault: false,
      controls: { polygon: true, trash: true },
      defaultMode: mode,
    });
    drawRef.current = draw;

    map.on("load", () => {
      if (references && references.length > 0) {
        const data: FeatureCollection = {
          type: "FeatureCollection",
          features: references.map((r) => ({
            type: "Feature",
            properties: { kind: r.kind },
            geometry: r.geometry,
          })),
        };
        map.addSource("references", { type: "geojson", data });
        map.addLayer({
          id: "references-fill",
          type: "fill",
          source: "references",
          filter: ["==", ["get", "kind"], "neighbour"],
          paint: { "fill-color": "#64748b", "fill-opacity": 0.35 },
        });
        map.addLayer({
          id: "references-line",
          type: "line",
          source: "references",
          paint: {
            "line-color": ["match", ["get", "kind"], "frame", "#16a34a", "#475569"],
            "line-width": ["match", ["get", "kind"], "frame", 3, 1.5],
            "line-dasharray": [2, 1],
          },
        });
        if (!initial) {
          const frame = references.find((r) => r.kind === "frame") ?? references[0];
          const [minX, minY, maxX, maxY] = bboxOfGeometry(frame.geometry);
          map.fitBounds(
            [
              [minX, minY],
              [maxX, maxY],
            ],
            { padding: 40, duration: 0 },
          );
        }
      }
      map.addControl(draw as unknown as maplibregl.IControl, "top-left");
      if (initial) {
        const feature: Feature = { type: "Feature", properties: {}, geometry: initial };
        draw.add(feature);
      }
    });

    const emit = (): void => {
      if (!onChange) return;
      const fc = draw.getAll();
      const f = fc.features.find((feat) => feat.geometry?.type === "Polygon");
      onChange(f ? (f.geometry as Polygon) : null);
    };
    map.on("draw.create", emit);
    map.on("draw.update", emit);
    map.on("draw.delete", emit);

    return () => {
      map.remove();
      mapRef.current = null;
      drawRef.current = null;
    };
    // initial/onChange/mode/references are read at mount; deliberately not re-running.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div
      ref={containerRef}
      data-testid="map-draw"
      className={className ?? "h-96 w-full overflow-hidden rounded-md border border-ap-line"}
    />
  );
}

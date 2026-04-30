import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import MapboxDraw from "@mapbox/mapbox-gl-draw";
import type { Feature, Polygon } from "geojson";

import { centerOfBbox } from "@/lib/geometry";

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

interface Props {
  initial?: Polygon | null;
  mode?: "draw_polygon" | "simple_select";
  onChange?: (polygon: Polygon | null) => void;
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
  className,
}: Props): JSX.Element {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const drawRef = useRef<MapboxDraw | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const center = initial ? centerOfBbox(initial) : DEFAULT_CENTER;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: RASTER_STYLE,
      center,
      zoom: initial ? 13 : DEFAULT_ZOOM,
    });
    mapRef.current = map;

    const draw = new MapboxDraw({
      displayControlsDefault: false,
      controls: { polygon: true, trash: true },
      defaultMode: mode,
    });
    drawRef.current = draw;

    map.on("load", () => {
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
    // initial/onChange/mode are read at mount; deliberately not re-running.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div
      ref={containerRef}
      data-testid="map-draw"
      className={className ?? "h-96 w-full overflow-hidden rounded-md border border-slate-200"}
    />
  );
}

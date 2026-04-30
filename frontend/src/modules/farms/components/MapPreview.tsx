import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import type { Geometry } from "geojson";

import { centerOfBbox } from "@/lib/geometry";

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
  geometry: Geometry | null | undefined;
  className?: string;
}

/** Read-only preview map that renders a single geometry. */
export function MapPreview({ geometry, className }: Props): JSX.Element {
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!ref.current || !geometry) return;
    const center = centerOfBbox(geometry);
    const map = new maplibregl.Map({
      container: ref.current,
      style: RASTER_STYLE,
      center,
      zoom: 12,
      interactive: false,
    });
    map.on("load", () => {
      map.addSource("aoi", {
        type: "geojson",
        data: { type: "Feature", properties: {}, geometry },
      });
      map.addLayer({
        id: "aoi-fill",
        type: "fill",
        source: "aoi",
        paint: { "fill-color": "#16a34a", "fill-opacity": 0.25 },
      });
      map.addLayer({
        id: "aoi-line",
        type: "line",
        source: "aoi",
        paint: { "line-color": "#16a34a", "line-width": 2 },
      });
    });
    return () => map.remove();
  }, [geometry]);

  return (
    <div
      ref={ref}
      data-testid="map-preview"
      className={className ?? "h-64 w-full overflow-hidden rounded-md border border-slate-200"}
    />
  );
}

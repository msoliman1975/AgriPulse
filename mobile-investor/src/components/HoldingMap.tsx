import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef, type ReactNode } from "react";

import type { Geometry } from "@/api/client";

const IMAGERY =
  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";

/** Every [lon, lat] pair in a GeoJSON coordinates array. */
function positions(coords: unknown, out: number[][] = []): number[][] {
  if (Array.isArray(coords) && typeof coords[0] === "number") out.push(coords as number[]);
  else if (Array.isArray(coords)) coords.forEach((c) => positions(c, out));
  return out;
}

/**
 * The holding outline over its block's outline, on a satellite basemap
 * (design option 1: sharp, but the image date is unknown).
 */
export function HoldingMap({ holding, block }: { holding: Geometry; block: Geometry }): ReactNode {
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const feature = (geometry: Geometry) =>
      ({ type: "Feature", properties: {}, geometry }) as GeoJSON.Feature;
    const map = new maplibregl.Map({
      container: el,
      attributionControl: { compact: true },
      style: {
        version: 8,
        sources: {
          imagery: {
            type: "raster",
            tiles: [IMAGERY],
            tileSize: 256,
            maxzoom: 19,
            attribution: "Esri World Imagery",
          },
          block: { type: "geojson", data: feature(block) },
          holding: { type: "geojson", data: feature(holding) },
        },
        layers: [
          { id: "imagery", type: "raster", source: "imagery" },
          {
            id: "block-line",
            type: "line",
            source: "block",
            paint: {
              "line-color": "#ffffff",
              "line-width": 2,
              "line-dasharray": ["literal", [2, 2]],
            },
          },
          {
            id: "holding-fill",
            type: "fill",
            source: "holding",
            paint: { "fill-color": "#facc15", "fill-opacity": 0.3 },
          },
          {
            id: "holding-line",
            type: "line",
            source: "holding",
            paint: { "line-color": "#facc15", "line-width": 3 },
          },
        ],
      },
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");

    // Fit the block, so the holding is seen in its place.
    const pts = positions(block.coordinates, positions(holding.coordinates));
    if (pts.length > 0) {
      const xs = pts.map((p) => p[0]);
      const ys = pts.map((p) => p[1]);
      map.fitBounds(
        [
          [Math.min(...xs), Math.min(...ys)],
          [Math.max(...xs), Math.max(...ys)],
        ],
        { padding: 32, duration: 0, maxZoom: 18 },
      );
    }
    const resize = new ResizeObserver(() => map.resize());
    resize.observe(el);
    return () => {
      resize.disconnect();
      map.remove();
    };
  }, [holding, block]);

  return <div ref={ref} className="map" />;
}

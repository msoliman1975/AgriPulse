import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef, type ReactNode } from "react";

import type { Geometry } from "@/api/client";
import { fetchCaptureDate } from "@/components/imageryDate";

const IMAGERY =
  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";

/** The outer rings of a Polygon or MultiPolygon. */
function outerRings(g: Geometry): number[][][] {
  if (g.type === "Polygon") return [(g.coordinates as number[][][])[0]];
  if (g.type === "MultiPolygon") return (g.coordinates as number[][][][]).map((p) => p[0]);
  return [];
}

/**
 * The block with the holding cut out: what the map dims. Each block ring is
 * an outer ring, and every holding ring is a hole in the first of them. The
 * holding always sits inside its block, so the holes fall inside.
 */
export function blockWithoutHolding(block: Geometry, holding: Geometry): GeoJSON.Feature {
  const blockRings = outerRings(block);
  const holes = outerRings(holding);
  const polygons = blockRings.map((ring, i) => (i === 0 ? [ring, ...holes] : [ring]));
  return {
    type: "Feature",
    properties: {},
    geometry: { type: "MultiPolygon", coordinates: polygons },
  };
}

/** Every [lon, lat] pair in a GeoJSON coordinates array. */
function positions(coords: unknown, out: number[][] = []): number[][] {
  if (Array.isArray(coords) && typeof coords[0] === "number") out.push(coords as number[]);
  else if (Array.isArray(coords)) coords.forEach((c) => positions(c, out));
  return out;
}

const PHOTO = "latest-photo";

/** Add, show or hide the latest-photo layer, just above the Esri base. */
type Bounds = [number, number, number, number];

function applyPhoto(
  map: maplibregl.Map,
  tileUrl: string | null,
  visible: boolean,
  bounds: Bounds | null,
): void {
  if (!tileUrl) return;
  if (!map.getSource(PHOTO)) {
    map.addSource(PHOTO, {
      type: "raster",
      tiles: [tileUrl],
      tileSize: 512,
      // Only tiles over the farm: each one outside it is an empty render.
      ...(bounds ? { bounds } : {}),
      attribution: "Contains modified Copernicus Sentinel data",
    });
    map.addLayer({ id: PHOTO, type: "raster", source: PHOTO }, "block-dim");
  }
  map.setLayoutProperty(PHOTO, "visibility", visible ? "visible" : "none");
}

/**
 * The holding outline over its block's outline, on Esri's sharp satellite
 * mosaic, with our newest clear Sentinel-2 photo over the farm when there is
 * one. `onBaseDate` reports when the Esri image under the holding was taken.
 */
export function HoldingMap({
  holding,
  block,
  photoTileUrl = null,
  photoBounds = null,
  showPhoto = true,
  onBaseDate,
}: {
  holding: Geometry;
  block: Geometry;
  photoTileUrl?: string | null;
  photoBounds?: Bounds | null;
  showPhoto?: boolean;
  onBaseDate?: (date: string | null) => void;
}): ReactNode {
  const ref = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const loadedRef = useRef(false);
  const onBaseDateRef = useRef(onBaseDate);
  onBaseDateRef.current = onBaseDate;
  const photoTileRef = useRef({ url: photoTileUrl, visible: showPhoto, bounds: photoBounds });
  photoTileRef.current = { url: photoTileUrl, visible: showPhoto, bounds: photoBounds };

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
          dim: { type: "geojson", data: blockWithoutHolding(block, holding) },
          holding: { type: "geojson", data: feature(holding) },
        },
        layers: [
          { id: "imagery", type: "raster", source: "imagery" },
          // The rest of the block, dimmed, so the holding stands out.
          {
            id: "block-dim",
            type: "fill",
            source: "dim",
            paint: { "fill-color": "#000000", "fill-opacity": 0.5 },
          },
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
            id: "holding-line",
            type: "line",
            source: "holding",
            paint: { "line-color": "#facc15", "line-width": 3 },
          },
        ],
      },
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");

    // Open on the holding; the dimmed block around it shows where it sits.
    const pts = positions(holding.coordinates);
    if (pts.length > 0) {
      const xs = pts.map((p) => p[0]);
      const ys = pts.map((p) => p[1]);
      const lon = (Math.min(...xs) + Math.max(...xs)) / 2;
      const lat = (Math.min(...ys) + Math.max(...ys)) / 2;
      void fetchCaptureDate(lon, lat).then((d) => onBaseDateRef.current?.(d));
      map.fitBounds(
        [
          [Math.min(...xs), Math.min(...ys)],
          [Math.max(...xs), Math.max(...ys)],
        ],
        { padding: 56, duration: 0, maxZoom: 19 },
      );
    }
    mapRef.current = map;
    map.on("load", () => {
      loadedRef.current = true;
      const p = photoTileRef.current;
      applyPhoto(map, p.url, p.visible, p.bounds);
    });
    const resize = new ResizeObserver(() => map.resize());
    resize.observe(el);
    return () => {
      resize.disconnect();
      loadedRef.current = false;
      mapRef.current = null;
      map.remove();
    };
  }, [holding, block]);

  // The photo arrives after the map; laying it on later keeps the view.
  useEffect(() => {
    const map = mapRef.current;
    if (map && loadedRef.current) applyPhoto(map, photoTileUrl, showPhoto, photoBounds);
    // photoBounds arrives with photoTileUrl, so the URL is enough to re-run.
  }, [photoTileUrl, showPhoto]);

  return <div ref={ref} className="map" />;
}

import maplibregl from "maplibre-gl";
import { useEffect, useRef, type ReactNode } from "react";
import type { Geometry } from "geojson";

import { centerOfBbox } from "@/lib/geometry";

/**
 * The scene's index raster with the block outline over it, and a click
 * handler that hands back the coordinate of whatever the operator pointed at.
 *
 * Plain MapLibre rather than the deck.gl overlay `NDVIMap` uses: this map
 * exists to be clicked, and a raster source is a smaller surface than a
 * TileLayer for the one thing that matters here — turning a click into a
 * lon/lat the pixel-explain endpoint can resolve.
 */

const BASE_STYLE: maplibregl.StyleSpecification = {
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
  geometry: Geometry;
  /** TiTiler XYZ template, or null while no index is selected. */
  tileUrlTemplate: string | null;
  picked: { lon: number; lat: number } | null;
  onPick: (point: { lon: number; lat: number }) => void;
  className?: string;
}

export function ObserverSceneMap({
  geometry,
  tileUrlTemplate,
  picked,
  onPick,
  className,
}: Props): ReactNode {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markerRef = useRef<maplibregl.Marker | null>(null);
  // The click handler closes over `onPick`; keeping it in a ref means the
  // map is built once and never torn down just because the parent
  // re-rendered with a new callback identity.
  const onPickRef = useRef(onPick);
  onPickRef.current = onPick;

  useEffect(() => {
    if (!containerRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: BASE_STYLE,
      center: centerOfBbox(geometry),
      zoom: 14,
    });
    mapRef.current = map;

    map.on("load", () => {
      map.addSource("aoi", {
        type: "geojson",
        data: { type: "Feature", properties: {}, geometry },
      });
      map.addLayer({
        id: "aoi-line",
        type: "line",
        source: "aoi",
        paint: { "line-color": "#16a34a", "line-width": 2 },
      });
    });

    map.on("click", (e) => {
      onPickRef.current({ lon: e.lngLat.lng, lat: e.lngLat.lat });
    });
    map.getCanvas().style.cursor = "crosshair";

    return () => {
      markerRef.current?.remove();
      markerRef.current = null;
      mapRef.current = null;
      map.remove();
    };
    // Rebuilding on a new geometry is correct — that is a different block.
  }, [geometry]);

  // Swap the raster without remounting, so a pan/zoom survives an index change.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = (): void => {
      if (map.getLayer("index-raster")) map.removeLayer("index-raster");
      if (map.getSource("index-raster")) map.removeSource("index-raster");
      if (!tileUrlTemplate) return;
      map.addSource("index-raster", {
        type: "raster",
        tiles: [tileUrlTemplate],
        tileSize: 256,
      });
      map.addLayer(
        {
          id: "index-raster",
          type: "raster",
          source: "index-raster",
          paint: { "raster-opacity": 0.8 },
        },
        // Keep the block outline on top of the raster.
        map.getLayer("aoi-line") ? "aoi-line" : undefined,
      );
    };
    if (map.isStyleLoaded()) apply();
    // maplibre types `once` as promise-returning when called without a
    // listener; with one it is fire-and-forget, so discard explicitly.
    else void map.once("load", apply);
  }, [tileUrlTemplate]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    markerRef.current?.remove();
    markerRef.current = null;
    if (!picked) return;
    markerRef.current = new maplibregl.Marker({ color: "#1f6f9a" })
      .setLngLat([picked.lon, picked.lat])
      .addTo(map);
  }, [picked]);

  return <div ref={containerRef} className={className ?? "h-96 w-full rounded"} />;
}

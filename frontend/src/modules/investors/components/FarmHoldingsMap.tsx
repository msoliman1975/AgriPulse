import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import type { FeatureCollection } from "geojson";

import type { FarmMapBlock, Holding } from "@/api/investors";
import { HOLDING_STATUS_COLOR } from "../lib";

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
  blocks: FarmMapBlock[];
  holdings: Holding[];
  /** Drawn with a thick outline: the block picked for a new holding. */
  selectedBlockId?: string | null;
  onBlockClick?: (blockId: string) => void;
  onHoldingClick?: (holdingId: string) => void;
  className?: string;
}

/**
 * Every active block of one farm, with its holdings coloured by status.
 * A click on a holding wins over a click on the block under it.
 */
export function FarmHoldingsMap({
  blocks,
  holdings,
  selectedBlockId,
  onBlockClick,
  onHoldingClick,
  className,
}: Props): JSX.Element {
  const ref = useRef<HTMLDivElement | null>(null);
  // Kept in refs so a new callback each render does not rebuild the map.
  const onBlockRef = useRef(onBlockClick);
  const onHoldingRef = useRef(onHoldingClick);
  onBlockRef.current = onBlockClick;
  onHoldingRef.current = onHoldingClick;

  useEffect(() => {
    if (!ref.current || blocks.length === 0) return;
    const bounds = new maplibregl.LngLatBounds();
    for (const b of blocks) {
      for (const [x, y] of b.boundary.coordinates[0]) bounds.extend([x, y]);
    }
    const map = new maplibregl.Map({
      container: ref.current,
      style: RASTER_STYLE,
      bounds,
      fitBoundsOptions: { padding: 30 },
    });
    const blockData: FeatureCollection = {
      type: "FeatureCollection",
      features: blocks.map((b) => ({
        type: "Feature",
        properties: {
          id: b.id,
          selected: b.id === selectedBlockId ? 1 : 0,
          eligible: b.eligible ? 1 : 0,
        },
        geometry: b.boundary,
      })),
    };
    const holdingData: FeatureCollection = {
      type: "FeatureCollection",
      features: holdings.map((h) => ({
        type: "Feature",
        properties: { id: h.id, color: HOLDING_STATUS_COLOR[h.status] },
        geometry: h.boundary,
      })),
    };
    // The box can still be settling when the map is built (the page swaps a
    // skeleton for content), so measure again on load and on every resize,
    // and fit after the first real measurement.
    const resize = new ResizeObserver(() => map.resize());
    resize.observe(ref.current);
    map.on("load", () => {
      map.resize();
      map.fitBounds(bounds, { padding: 30, duration: 0 });
      map.addSource("blocks", { type: "geojson", data: blockData });
      map.addLayer({
        id: "blocks-fill",
        type: "fill",
        source: "blocks",
        paint: {
          "fill-color": "#16a34a",
          "fill-opacity": ["case", ["==", ["get", "selected"], 1], 0.25, 0.08],
        },
      });
      map.addLayer({
        id: "blocks-line",
        type: "line",
        source: "blocks",
        paint: {
          "line-color": "#16a34a",
          "line-width": ["case", ["==", ["get", "selected"], 1], 3, 1.5],
          "line-dasharray": ["literal", [2, 1]],
        },
      });
      map.addSource("holdings", { type: "geojson", data: holdingData });
      map.addLayer({
        id: "holdings-fill",
        type: "fill",
        source: "holdings",
        paint: { "fill-color": ["get", "color"], "fill-opacity": 0.55 },
      });
      map.addLayer({
        id: "holdings-line",
        type: "line",
        source: "holdings",
        paint: { "line-color": "#0f172a", "line-width": 1 },
      });
      map.on("click", (e) => {
        const hit = map.queryRenderedFeatures(e.point, { layers: ["holdings-fill"] })[0];
        const holdingId: unknown = hit?.properties?.id;
        if (typeof holdingId === "string" && onHoldingRef.current) {
          onHoldingRef.current(holdingId);
          return;
        }
        const block = map.queryRenderedFeatures(e.point, { layers: ["blocks-fill"] })[0];
        const blockId: unknown = block?.properties?.id;
        if (typeof blockId === "string" && onBlockRef.current) onBlockRef.current(blockId);
      });
      map.on("mousemove", (e) => {
        const n = map.queryRenderedFeatures(e.point, {
          layers: ["holdings-fill", "blocks-fill"],
        }).length;
        map.getCanvas().style.cursor = n > 0 ? "pointer" : "";
      });
    });
    return () => {
      resize.disconnect();
      map.remove();
    };
  }, [blocks, holdings, selectedBlockId]);

  return (
    <div
      ref={ref}
      data-testid="farm-holdings-map"
      className={className ?? "h-96 w-full overflow-hidden rounded-md border border-ap-line"}
    />
  );
}

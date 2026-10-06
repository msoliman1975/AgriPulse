import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import type { FeatureCollection, Polygon } from "geojson";

import type { Holding } from "@/api/investors";
import { bboxOfGeometry, centerOfBbox } from "@/lib/geometry";
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
  block: Polygon;
  holdings: Holding[];
  /** Drawn with a thick outline: the holding the page is about. */
  highlightId?: string;
  onSelect?: (holdingId: string) => void;
  className?: string;
}

/**
 * Read-only map of one block and its holdings, coloured by status. Staff use
 * it to see what is sold and what is left; it is not the investor's map.
 */
export function HoldingsMap({
  block,
  holdings,
  highlightId,
  onSelect,
  className,
}: Props): JSX.Element {
  const ref = useRef<HTMLDivElement | null>(null);
  // Kept in a ref so a new callback each render does not rebuild the map.
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const selectable = Boolean(onSelect);

  useEffect(() => {
    if (!ref.current) return;
    const map = new maplibregl.Map({
      container: ref.current,
      style: RASTER_STYLE,
      center: centerOfBbox(block),
      zoom: 15,
    });
    const data: FeatureCollection = {
      type: "FeatureCollection",
      features: holdings.map((h) => ({
        type: "Feature",
        properties: {
          id: h.id,
          code: h.code,
          color: HOLDING_STATUS_COLOR[h.status],
          highlight: h.id === highlightId ? 1 : 0,
        },
        geometry: h.boundary,
      })),
    };
    const resize = new ResizeObserver(() => map.resize());
    resize.observe(ref.current);
    map.on("load", () => {
      map.resize();
      const [minX, minY, maxX, maxY] = bboxOfGeometry(block);
      map.fitBounds(
        [
          [minX, minY],
          [maxX, maxY],
        ],
        { padding: 30, duration: 0 },
      );
      map.addSource("block", {
        type: "geojson",
        data: { type: "Feature", properties: {}, geometry: block },
      });
      map.addLayer({
        id: "block-line",
        type: "line",
        source: "block",
        paint: { "line-color": "#16a34a", "line-width": 3, "line-dasharray": [2, 1] },
      });
      map.addSource("holdings", { type: "geojson", data });
      map.addLayer({
        id: "holdings-fill",
        type: "fill",
        source: "holdings",
        paint: { "fill-color": ["get", "color"], "fill-opacity": 0.45 },
      });
      map.addLayer({
        id: "holdings-line",
        type: "line",
        source: "holdings",
        paint: {
          "line-color": "#0f172a",
          "line-width": ["case", ["==", ["get", "highlight"], 1], 3, 1],
        },
      });
      if (selectable) {
        map.on("click", "holdings-fill", (e) => {
          const id: unknown = e.features?.[0]?.properties?.id;
          if (typeof id === "string") onSelectRef.current?.(id);
        });
        map.on("mouseenter", "holdings-fill", () => {
          map.getCanvas().style.cursor = "pointer";
        });
        map.on("mouseleave", "holdings-fill", () => {
          map.getCanvas().style.cursor = "";
        });
      }
    });
    return () => {
      resize.disconnect();
      map.remove();
    };
  }, [block, holdings, highlightId, selectable]);

  return (
    <div
      ref={ref}
      data-testid="holdings-map"
      className={className ?? "h-72 w-full overflow-hidden rounded-md border border-ap-line"}
    />
  );
}

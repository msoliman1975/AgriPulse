import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import { MapboxOverlay } from "@deck.gl/mapbox";
import { TileLayer } from "@deck.gl/geo-layers";
import { BitmapLayer } from "@deck.gl/layers";
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
  /** AOI polygon, in WGS84. Drawn under the raster as a vector overlay. */
  geometry: Geometry | null | undefined;
  /** TiTiler tile-URL template with `{z}/{x}/{y}` placeholders, or null. */
  tileUrlTemplate: string | null;
  className?: string;
}

/**
 * MapLibre base map + AOI vector outline + a deck.gl `TileLayer` that
 * renders one COG's tiles as a raster overlay. Imported lazily by
 * `ImageryPanel` so unit tests of the panel can mock just this
 * component (deck.gl + MapLibre both need WebGL, which jsdom doesn't
 * provide).
 */
export function NDVIMap({ geometry, tileUrlTemplate, className }: Props): JSX.Element {
  const ref = useRef<HTMLDivElement | null>(null);
  const overlayRef = useRef<MapboxOverlay | null>(null);

  useEffect(() => {
    if (!ref.current || !geometry) return;
    const center = centerOfBbox(geometry);
    const map = new maplibregl.Map({
      container: ref.current,
      style: RASTER_STYLE,
      center,
      zoom: 12,
    });
    map.on("load", () => {
      // AOI vector layer.
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

      // deck.gl overlay attached as a MapLibre control.
      const overlay = new MapboxOverlay({
        interleaved: false,
        layers: [],
      });
      // Use map.addControl for proper lifecycle handling — deck.gl's
      // recommended pattern with MapLibre. MapboxOverlay implements
      // the IControl interface that MapLibre also accepts.
      map.addControl(overlay);
      overlayRef.current = overlay;

      applyOverlay(overlay, tileUrlTemplate);
    });

    return () => {
      overlayRef.current = null;
      map.remove();
    };
    // We deliberately omit `tileUrlTemplate` from this effect — applying
    // it on subsequent changes is handled by the next effect, which
    // doesn't tear the map down.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [geometry]);

  // Subsequent NDVI URL changes update the overlay without re-mounting
  // the map (would otherwise lose the user's pan/zoom).
  useEffect(() => {
    const overlay = overlayRef.current;
    if (!overlay) return;
    applyOverlay(overlay, tileUrlTemplate);
  }, [tileUrlTemplate]);

  return <div ref={ref} className={className ?? "h-72 w-full rounded"} />;
}

function applyOverlay(overlay: MapboxOverlay, tileUrlTemplate: string | null): void {
  if (tileUrlTemplate === null) {
    overlay.setProps({ layers: [] });
    return;
  }
  const tileLayer = new TileLayer({
    id: "ndvi-tiles",
    data: tileUrlTemplate,
    minZoom: 0,
    maxZoom: 22,
    tileSize: 256,
    // deck.gl's TileLayer typings widen `boundingBox` to a 2D array; we
    // narrow at runtime since the consumer only needs four numbers.
    renderSubLayers: (props) => {
      const tile = (props as { tile: { boundingBox: number[][] } }).tile;
      const [[west, south], [east, north]] = tile.boundingBox as [
        [number, number],
        [number, number],
      ];
      return new BitmapLayer({
        id: `${props.id}-bmp`,
        image: (props as { data: string }).data,
        bounds: [west, south, east, north],
        opacity: 0.75,
      });
    },
  });
  overlay.setProps({ layers: [tileLayer] });
}

import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import MapboxDraw from "@mapbox/mapbox-gl-draw";
import type { Feature, FeatureCollection, Polygon } from "geojson";

import { DRAW_STYLES, applyMapLibreClassesToDraw } from "@/lib/drawStyles";
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
  /** Label for the button that removes the shape and starts drawing again. */
  clearLabel?: string;
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
  clearLabel,
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

    applyMapLibreClassesToDraw(MapboxDraw);
    const draw = new MapboxDraw({
      displayControlsDefault: false,
      controls: { polygon: true, trash: true },
      defaultMode: mode,
      styles: DRAW_STYLES,
    });
    drawRef.current = draw;

    // The box can still be settling when the map is built; measure again on
    // load and on every resize, or the canvas fills one corner.
    const resize = new ResizeObserver(() => map.resize());
    resize.observe(containerRef.current);

    map.on("load", () => {
      map.resize();
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
            "line-dasharray": ["literal", [2, 1]],
          },
        });
        if (!initial) {
          // Fit every frame (all blocks of a farm), not only the first one.
          const frames = references.filter((r) => r.kind === "frame");
          const boxes = (frames.length > 0 ? frames : references).map((r) =>
            bboxOfGeometry(r.geometry),
          );
          const minX = Math.min(...boxes.map((b) => b[0]));
          const minY = Math.min(...boxes.map((b) => b[1]));
          const maxX = Math.max(...boxes.map((b) => b[2]));
          const maxY = Math.max(...boxes.map((b) => b[3]));
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
    // One shape at a time: a new shape replaces the previous one.
    map.on("draw.create", (e: { features: Feature[] }) => {
      const keep = new Set(e.features.map((f) => String(f.id)));
      const stale = draw
        .getAll()
        .features.map((f) => String(f.id))
        .filter((id) => !keep.has(id));
      if (stale.length > 0) draw.delete(stale);
      emit();
    });
    map.on("draw.update", emit);
    map.on("draw.delete", emit);

    return () => {
      resize.disconnect();
      map.remove();
      mapRef.current = null;
      drawRef.current = null;
    };
    // initial/onChange/mode/references are read at mount; deliberately not re-running.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const clear = (): void => {
    const draw = drawRef.current;
    if (!draw) return;
    draw.deleteAll();
    draw.changeMode("draw_polygon");
    onChange?.(null);
  };

  return (
    <div className="relative">
      <div
        ref={containerRef}
        data-testid="map-draw"
        className={className ?? "h-96 w-full overflow-hidden rounded-md border border-ap-line"}
      />
      {clearLabel ? (
        <button
          type="button"
          onClick={clear}
          className="absolute end-2 top-2 rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-xs font-medium text-ap-ink shadow-sm hover:bg-ap-line/40"
        >
          {clearLabel}
        </button>
      ) : null}
    </div>
  );
}

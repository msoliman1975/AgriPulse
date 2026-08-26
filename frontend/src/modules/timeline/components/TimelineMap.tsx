// The replay canvas: index pixels for the frame's pass, block outlines,
// and the day's marks.
//
// A lean map of its own rather than the Farm Console's `MapCanvas`. That
// component carries drawing, reshaping, grid cells, health fills and a
// forty-prop surface, none of which a read-only replay wants — and every
// one of which would have to be switched off from here, which is a change
// to a screen this work is not allowed to touch. What IS shared is the
// part that must not drift: the marker artwork (`registerMarkerImages`)
// and the tile-URL rules (`pixelTiles`), both imported.

import { useEffect, useRef } from "react";
import maplibregl, {
  type GeoJSONSource,
  type LngLatBoundsLike,
  type Map as MlMap,
  type StyleSpecification,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { FeatureCollection, MultiPolygon, Point, Polygon } from "geojson";

import { registerMarkerImages } from "@/modules/labs/map/markerIcons";
import { TILE_SIZE } from "@/modules/labs/console/pixelTiles";
import type { MarkProps } from "../lib/marks";
import { rasterSourceSpec } from "../lib/rasterSource";

/** One raster to draw for the current pass. */
export interface RasterLayer {
  /** Stable within a pass — the block id, or `__farm__` for a farm raster. */
  id: string;
  /** XYZ template with `{z}/{x}/{y}` intact. */
  tileUrl: string;
  /**
   * `[west, south, east, north]`. Bounding each block's source is what
   * stops 35 sources from each requesting tiles across the whole farm —
   * without it a farm-wide view costs 35x the tiles it needs.
   */
  bounds?: [number, number, number, number];
}

export interface BlockFeatureProps {
  block_id: string;
  block_name: string;
  /** 0..1 from the block-highlight fade; 0 means no event stands on it. */
  highlight: number;
}

interface Props {
  blocks: FeatureCollection<Polygon, BlockFeatureProps>;
  farmBoundary: MultiPolygon | null;
  rasters: readonly RasterLayer[];
  marks: FeatureCollection<Point, MarkProps>;
  /** Bump to refit the view. Pass the farm id (plus the block, in block scope). */
  fitKey: string;
  onMarkClick?: (eventId: string) => void;
}

const AOI_SOURCE = "tl-aoi";
const AOI_LINE = "tl-aoi-line";
const BLOCK_SOURCE = "tl-blocks";
const BLOCK_LINE = "tl-blocks-line";
const BLOCK_HIGHLIGHT = "tl-blocks-highlight";
const MARK_SOURCE = "tl-marks";
const MARK_LAYER = "tl-marks-symbols";

/** Prefix for every raster layer/source this component owns. */
const RASTER_PREFIX = "tl-raster-";

const EMPTY: FeatureCollection<Point, MarkProps> = { type: "FeatureCollection", features: [] };

function buildStyle(): StyleSpecification {
  return {
    version: 8,
    // Only the AOI/block lines need glyphs, and neither carries text. The
    // endpoint is declared anyway so a future label does not silently fail.
    glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
    sources: {
      satellite: {
        type: "raster",
        tiles: [
          "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        ],
        tileSize: 256,
        attribution:
          "Tiles © Esri — Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, " +
          "Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community",
        maxzoom: 19,
      },
    },
    layers: [
      { id: "background", type: "background", paint: { "background-color": "#b5ad8e" } },
      {
        id: "satellite",
        type: "raster",
        source: "satellite",
        paint: { "raster-opacity": 1, "raster-resampling": "linear" },
      },
    ],
  };
}

function boundsOf(
  blocks: FeatureCollection<Polygon, BlockFeatureProps>,
  farmBoundary: MultiPolygon | null,
): LngLatBoundsLike | null {
  let west = Infinity;
  let south = Infinity;
  let east = -Infinity;
  let north = -Infinity;
  const visit = (ring: number[][]): void => {
    for (const [lon, lat] of ring) {
      if (lon < west) west = lon;
      if (lon > east) east = lon;
      if (lat < south) south = lat;
      if (lat > north) north = lat;
    }
  };
  for (const f of blocks.features) for (const ring of f.geometry.coordinates) visit(ring);
  if (farmBoundary) for (const poly of farmBoundary.coordinates) for (const r of poly) visit(r);
  if (!Number.isFinite(west) || !Number.isFinite(south)) return null;
  return [
    [west, south],
    [east, north],
  ];
}

export function TimelineMap({
  blocks,
  farmBoundary,
  rasters,
  marks,
  fitKey,
  onMarkClick,
}: Props): React.ReactElement {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MlMap | null>(null);
  const readyRef = useRef(false);
  const lastFitRef = useRef<string | null>(null);
  const onMarkClickRef = useRef(onMarkClick);
  onMarkClickRef.current = onMarkClick;

  // The raster set currently on the map, and the generation it belongs to.
  // Swapping passes replaces every layer at once; see the effect below.
  const rasterGenRef = useRef(0);
  const liveRasterIdsRef = useRef<string[]>([]);

  // Latest props, read by the `load` handler. The map mounts once, so
  // without these the first paint would use whatever the first render saw.
  const latestRef = useRef({ blocks, farmBoundary, marks, rasters, fitKey });
  latestRef.current = { blocks, farmBoundary, marks, rasters, fitKey };

  // ---- mount ------------------------------------------------------------
  useEffect(() => {
    if (!containerRef.current) return;
    const initial = latestRef.current;
    const initialBounds = boundsOf(initial.blocks, initial.farmBoundary);
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: buildStyle(),
      center: [31.0, 30.5],
      zoom: 13,
      // Framed at construction rather than flown to after the first data
      // effect, so opening the screen does not start with a zoom-in flash.
      bounds: initialBounds ?? undefined,
      fitBoundsOptions: { padding: 48 },
      attributionControl: { compact: true },
    });
    if (initialBounds) lastFitRef.current = initial.fitKey;
    mapRef.current = map;
    map.dragRotate.disable();
    map.touchZoomRotate.disableRotation();
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-left");

    // A side rail opening resizes this container, not the window, and
    // maplibre's trackResize only watches the window — so the canvas would
    // keep its old size and the map would appear to jump.
    const ro = new ResizeObserver(() => mapRef.current?.resize());
    ro.observe(containerRef.current);

    map.on("load", () => {
      // Artwork first. MapLibre resolves `icon-image` at draw time and a
      // symbol whose image is missing draws NOTHING, with no error — so
      // registering after the layers would leave the marks blank until
      // some later repaint happened to follow registration.
      registerMarkerImages(map);

      map.addSource(AOI_SOURCE, { type: "geojson", data: emptyPolygons() });
      map.addLayer({
        id: AOI_LINE,
        type: "line",
        source: AOI_SOURCE,
        paint: {
          "line-color": "#f8fafc",
          "line-width": 2,
          "line-dasharray": [3, 2],
          "line-opacity": 0.8,
        },
      });

      map.addSource(BLOCK_SOURCE, { type: "geojson", data: emptyPolygons() });
      // The highlight sits UNDER the outline so a lit block reads as a
      // glow inside its own border rather than as a thicker border.
      map.addLayer({
        id: BLOCK_HIGHLIGHT,
        type: "fill",
        source: BLOCK_SOURCE,
        paint: {
          "fill-color": "#facc15",
          // Driven by the feature's own `highlight`, so one source update
          // per frame moves every block. A style recompile per frame would
          // stall playback.
          "fill-opacity": ["*", ["get", "highlight"], 0.28],
        },
      });
      map.addLayer({
        id: BLOCK_LINE,
        type: "line",
        source: BLOCK_SOURCE,
        paint: {
          "line-color": [
            "case",
            [">", ["get", "highlight"], 0],
            "#facc15",
            "rgba(248, 250, 252, 0.75)",
          ],
          "line-width": ["case", [">", ["get", "highlight"], 0], 2.5, 1.2],
        },
      });

      map.addSource(MARK_SOURCE, { type: "geojson", data: EMPTY });
      map.addLayer({
        id: MARK_LAYER,
        type: "symbol",
        source: MARK_SOURCE,
        layout: {
          // Resolved in `marks.ts`, never by a `match` here, so the ids the
          // layer asks for and the ids registered above come from one place.
          "icon-image": ["get", "marker_icon"],
          // Marks take part in collision like everything else. An exempt
          // symbol (`ignore-placement: true`) also RESERVES NO SPACE, which
          // is how four overlays once piled onto one pixel and none of them
          // could be read.
          "icon-allow-overlap": false,
          "icon-ignore-placement": false,
          "icon-padding": 4,
          // Lower sorts first and first placed wins, so the freshest and
          // worst mark survives a crowded frame. Computed in `marks.ts`.
          "symbol-sort-key": ["get", "sort_key"],
          // Deliberately NO `text-field`. A symbol layer that carries text
          // cannot draw at all until the style's glyph endpoint answers, so
          // a label would make every mark vanish whenever fonts are slow.
        },
        paint: {
          "icon-opacity": ["get", "opacity"],
        },
      });

      map.on("click", MARK_LAYER, (e) => {
        const id = e.features?.[0]?.properties?.event_id;
        if (typeof id === "string") onMarkClickRef.current?.(id);
      });
      map.on("mouseenter", MARK_LAYER, () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", MARK_LAYER, () => {
        map.getCanvas().style.cursor = "";
      });

      readyRef.current = true;
      // Draw whatever the props say right now — the effects below only run
      // on change, and their first run already happened while `ready` was
      // false.
      const now = latestRef.current;
      applyAoi(map, now.farmBoundary);
      applyBlocks(map, now.blocks);
      applyMarks(map, now.marks);
      applyRasters(map, now.rasters, rasterGenRef, liveRasterIdsRef);
    });

    return () => {
      ro.disconnect();
      readyRef.current = false;
      map.remove();
      mapRef.current = null;
    };
    // Mount once. Every prop is applied by its own effect below.
  }, []);

  // ---- data effects -----------------------------------------------------

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !readyRef.current) return;
    applyAoi(map, farmBoundary);
  }, [farmBoundary]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !readyRef.current) return;
    applyBlocks(map, blocks);
  }, [blocks]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !readyRef.current) return;
    applyMarks(map, marks);
  }, [marks]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !readyRef.current) return;
    applyRasters(map, rasters, rasterGenRef, liveRasterIdsRef);
  }, [rasters]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !readyRef.current) return;
    if (lastFitRef.current === fitKey) return;
    const b = boundsOf(blocks, farmBoundary);
    if (!b) return;
    lastFitRef.current = fitKey;
    map.fitBounds(b, { padding: 48, duration: 400 });
  }, [fitKey, blocks, farmBoundary]);

  return <div ref={containerRef} className="h-full w-full" data-testid="timeline-map" />;
}

// ---------------------------------------------------------------------------
// Imperative helpers. Kept outside the component so the effects above read
// as a list of "what changed", not as map plumbing.
// ---------------------------------------------------------------------------

function emptyPolygons(): FeatureCollection<Polygon, Record<string, never>> {
  return { type: "FeatureCollection", features: [] };
}

function applyAoi(map: MlMap, farmBoundary: MultiPolygon | null): void {
  const src = map.getSource<GeoJSONSource>(AOI_SOURCE);
  if (!src) return;
  src.setData(
    farmBoundary
      ? {
          type: "FeatureCollection",
          features: [{ type: "Feature", geometry: farmBoundary, properties: {} }],
        }
      : { type: "FeatureCollection", features: [] },
  );
}

function applyBlocks(map: MlMap, blocks: FeatureCollection<Polygon, BlockFeatureProps>): void {
  const src = map.getSource<GeoJSONSource>(BLOCK_SOURCE);
  if (!src) return;
  src.setData(blocks);
}

function applyMarks(map: MlMap, marks: FeatureCollection<Point, MarkProps>): void {
  const src = map.getSource<GeoJSONSource>(MARK_SOURCE);
  if (!src) return;
  src.setData(marks);
}

/**
 * Swap the pixel layers for a new pass without a gap.
 *
 * The naive remove-then-add shows bare satellite for as long as the new
 * tiles take, and at four frames a second that flash lands every time the
 * play head crosses an acquisition. So the new generation is added FIRST,
 * under the block outlines, and the previous one is removed only once the
 * map goes idle — which is after the new tiles have painted.
 *
 * Generations are numbered rather than diffed by block id, because a
 * per-block farm and a farm-raster farm produce different id sets for the
 * same ground and a diff between them would leave one of each on screen.
 */
function applyRasters(
  map: MlMap,
  rasters: readonly RasterLayer[],
  genRef: { current: number },
  liveRef: { current: string[] },
): void {
  const previous = liveRef.current;
  genRef.current += 1;
  const gen = genRef.current;

  const added: string[] = [];
  for (const raster of rasters) {
    const layerId = `${RASTER_PREFIX}${gen}-${raster.id}`;
    if (map.getSource(layerId)) continue;
    // Built by `rasterSourceSpec` rather than inline, so the shape handed
    // to MapLibre is testable. An explicit `bounds: undefined` throws here
    // and takes the whole pixel layer with it; see that module for why.
    // 512 rather than 256 on tileSize: the cost is per REQUEST, not per
    // pixel, and `pixelTiles` already asks TiTiler for that size via `scale`.
    map.addSource(
      layerId,
      rasterSourceSpec({
        tileUrl: raster.tileUrl,
        bounds: raster.bounds,
        tileSize: TILE_SIZE,
      }),
    );
    map.addLayer(
      {
        id: layerId,
        type: "raster",
        source: layerId,
        paint: { "raster-opacity": 0.85, "raster-resampling": "linear" },
      },
      // Under the outlines and the marks, above the satellite.
      map.getLayer(BLOCK_HIGHLIGHT) ? BLOCK_HIGHLIGHT : undefined,
    );
    added.push(layerId);
  }
  liveRef.current = added;

  if (previous.length === 0) return;
  const drop = (): void => {
    for (const id of previous) {
      if (map.getLayer(id)) map.removeLayer(id);
      if (map.getSource(id)) map.removeSource(id);
    }
  };
  if (added.length === 0) {
    // Nothing to fade into — a frame before the first pass. Drop at once
    // rather than leaving the previous pass under a scrubber that says
    // there is no image yet.
    drop();
    return;
  }
  // `once` with a listener returns the map, but its overload set also
  // covers a promise form, so the call reads as floating without this.
  void map.once("idle", drop);
}

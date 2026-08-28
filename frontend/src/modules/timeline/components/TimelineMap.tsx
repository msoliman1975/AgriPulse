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
  type Map as MlMap,
  type StyleSpecification,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { FeatureCollection, MultiPolygon, Point, Polygon } from "geojson";

import { registerMarkerImages } from "@/modules/labs/map/markerIcons";
import type { MarkProps } from "../lib/marks";
import { boundsOf } from "../lib/mapBounds";
import { syncRasters, type RasterCache, type RasterFrame } from "../lib/rasterCache";

// Re-exported so callers keep importing the map's own vocabulary from the
// map. `rasterCache` is where they are DEFINED, because that module is the
// one a fake-map test can import.
export type { RasterFrame, RasterLayer } from "../lib/rasterCache";

export interface BlockFeatureProps {
  block_id: string;
  block_name: string;
  /** 0..1 from the block-highlight fade; 0 means no event stands on it. */
  highlight: number;
}

interface Props {
  blocks: FeatureCollection<Polygon, BlockFeatureProps>;
  farmBoundary: MultiPolygon | null;
  /** The active pass first is NOT assumed; `activeRasterKey` names it. */
  rasterFrames: readonly RasterFrame[];
  /** Which frame is painted. Null while no pass covers the current day. */
  activeRasterKey: string | null;
  marks: FeatureCollection<Point, MarkProps>;
  /** Off hides the block outlines and their event highlight. */
  showBlocks: boolean;
  /** Off hides the farm boundary. */
  showFarmBoundary: boolean;
  /** Off hides every index raster without discarding the preloaded tiles. */
  showPixels: boolean;
  /** Cross-fade length in ms. Shorter at high playback speeds. */
  fadeMs: number;
  /** Bump to refit the view. Pass the farm id (plus the block, in block scope). */
  fitKey: string;
  onMarkClick?: (eventId: string) => void;
}

const AOI_SOURCE = "tl-aoi";
const AOI_LINE = "tl-aoi-line";
const BLOCK_SOURCE = "tl-blocks";
const BLOCK_LINE = "tl-blocks-line";
const MARK_SOURCE = "tl-marks";
const MARK_LAYER = "tl-marks-symbols";

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

export function TimelineMap({
  blocks,
  farmBoundary,
  rasterFrames,
  activeRasterKey,
  marks,
  showBlocks,
  showFarmBoundary,
  showPixels,
  fadeMs,
  fitKey,
  onMarkClick,
}: Props): React.ReactElement {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MlMap | null>(null);
  const readyRef = useRef(false);
  const lastFitRef = useRef<string | null>(null);
  const onMarkClickRef = useRef(onMarkClick);
  onMarkClickRef.current = onMarkClick;

  // The raster frames on the map, keyed by pass, with the layer ids each
  // one owns. Insertion order is the eviction order.
  const frameCacheRef = useRef<RasterCache>(new Map());
  // Bumped on every sync, so a fade that was waiting for tiles can tell it
  // has been overtaken and must not paint a pass the reader has left.
  const syncGenRef = useRef(0);

  // Latest props, read by the `load` handler. The map mounts once, so
  // without these the first paint would use whatever the first render saw.
  const latestRef = useRef({
    blocks,
    farmBoundary,
    marks,
    rasterFrames,
    activeRasterKey,
    showBlocks,
    showFarmBoundary,
    showPixels,
    fadeMs,
    fitKey,
  });
  latestRef.current = {
    blocks,
    farmBoundary,
    marks,
    rasterFrames,
    activeRasterKey,
    showBlocks,
    showFarmBoundary,
    showPixels,
    fadeMs,
    fitKey,
  };

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

    // Read once, here, rather than in the cleanup: the lint rule is right
    // that a ref can change before a cleanup runs, and this one is the
    // cache of layers belonging to the map created in THIS effect.
    const frameCache = frameCacheRef.current;

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
      // No block fill. A lit block used to carry a yellow glow as well as a
      // yellow border; the glow sat on top of the index raster and gave the
      // reader two colours for one block. The border and the line width say
      // the same thing without covering the pixels.
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
      applyVisibility(map, now.showBlocks, now.showFarmBoundary);
      syncRasters(map, {
        frames: now.rasterFrames,
        activeKey: now.showPixels ? now.activeRasterKey : null,
        fadeMs: now.fadeMs,
        cache: frameCacheRef,
        genRef: syncGenRef,
        beforeLayerId: BLOCK_LINE,
      });

      // And FRAME it. This is the whole of the auto-focus fix.
      //
      // The fit effect below returns early while `readyRef` is false, and
      // `readyRef` is a ref, so becoming ready re-runs nothing. On a cold
      // load the blocks almost always arrive first — an API response beats
      // MapLibre's style fetch plus WebGL init — so the effect ran once
      // against an unready map, returned, and never fired again because
      // `blocks` did not change a second time. The map then sat on the
      // constructor's fallback centre, which is the middle of Egypt, and
      // the farm was somewhere off screen.
      //
      // `duration: 0`, not an animation: this is the first paint, so there
      // is no previous view worth flying from.
      const initialFit = boundsOf(now.blocks, now.farmBoundary);
      if (initialFit && lastFitRef.current !== now.fitKey) {
        lastFitRef.current = now.fitKey;
        map.fitBounds(initialFit, { padding: 48, duration: 0 });
      }
    });

    return () => {
      ro.disconnect();
      readyRef.current = false;
      map.remove();
      mapRef.current = null;
      // The cache indexes layers of a map that no longer exists. Leaving it
      // populated would make a remount believe every frame is already on.
      frameCache.clear();
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
    syncRasters(map, {
      frames: rasterFrames,
      // Turning pixels off paints nothing but keeps the cached frames, so
      // turning them back on is instant rather than a re-fetch.
      activeKey: showPixels ? activeRasterKey : null,
      fadeMs,
      cache: frameCacheRef,
      genRef: syncGenRef,
      beforeLayerId: BLOCK_LINE,
    });
  }, [rasterFrames, activeRasterKey, showPixels, fadeMs]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !readyRef.current) return;
    applyVisibility(map, showBlocks, showFarmBoundary);
  }, [showBlocks, showFarmBoundary]);

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
 * Show or hide the frame layers — the farm outline and the block outlines.
 *
 * `visibility` rather than opacity, because these are cheap vector layers
 * with nothing to preload; hiding them should also stop them being drawn.
 */
function applyVisibility(map: MlMap, showBlocks: boolean, showFarmBoundary: boolean): void {
  const set = (layerId: string, on: boolean): void => {
    if (map.getLayer(layerId)) {
      map.setLayoutProperty(layerId, "visibility", on ? "visible" : "none");
    }
  };
  set(AOI_LINE, showFarmBoundary);
  set(BLOCK_LINE, showBlocks);
}

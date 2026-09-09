// The Farm Health View canvas: blocks, the selected block's cells coloured
// by verdict, and the outline of the selected area.
//
// Its own map rather than the Farm Console's `MapCanvas`, for the same
// reason the Timeline has its own: that component carries drawing,
// reshaping, health fills and a forty-prop surface, none of which a
// read-only screen wants, and switching each off from here would be a
// change to a screen this work must not touch.
//
// The cells are an image, not a fill layer. MapLibre cannot blur a fill,
// and a 121-cell grid drawn as flat squares reads as pixel art. So the
// cells are painted into a canvas, blurred there, and pinned to the block's
// bounding box as an `image` source. A transparent fill layer over the real
// polygons keeps clicks and hover exact — the picture is smoothed, the
// geometry is not.

import { useEffect, useRef, useState } from "react";
import maplibregl, {
  type GeoJSONSource,
  type ImageSource,
  type Map as MlMap,
  type StyleSpecification,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Feature, FeatureCollection, Polygon } from "geojson";

import type { StatusCode } from "@/api/farmHealth";
import { areaBounds, farmBounds, boundsOfPolygon, padBounds, toLngLatBounds } from "../lib/fit";
import {
  bboxToImageCoordinates,
  blurRadius,
  canvasSize,
  cellsBbox,
  outlineSegments,
  paintCells,
  type PaintCell,
} from "../lib/cellRaster";

const BLOCK_SOURCE = "fh-blocks";
const CELL_IMAGE_SOURCE = "fh-cell-image";
const CELL_IMAGE_LAYER = "fh-cell-image";
const CELL_HIT_SOURCE = "fh-cell-hit";
const OUTLINE_SOURCE = "fh-outline";

/** A block outline, its verdict, and whether it is the one in focus. */
export interface MapBlock {
  blockId: string;
  code: string;
  boundary: Polygon;
  selected: boolean;
  /**
   * The worst verdict on this block for the chosen tree, or null when the
   * tree did not run here.
   *
   * A block-scoped tree writes one verdict for the whole block and no cells
   * at all, so this is the only colour such a tree can put on the map.
   */
  status: StatusCode | null;
}

/** A cell of the selected block: geometry, grid position and verdict. */
export interface MapCell {
  cellId: string;
  row: number;
  col: number;
  ring: [number, number][];
  status: StatusCode;
}

interface Props {
  blocks: MapBlock[];
  cells: MapCell[];
  /** Cell ids in the selected area. Outlined, unfiltered, on top. */
  highlighted: Set<string>;
  colorOf: (status: StatusCode) => string;
  onSelectBlock: (blockId: string) => void;
  onSelectCell: (cellId: string) => void;
  /**
   * What to frame. "block" follows the selection, "area" frames the open
   * area, "farm" shows every block and stops greying the unselected ones.
   */
  fitMode: FitMode;
  /** Changing this refits without changing the mode: pass the block id. */
  fitKey: string;
}

export type FitMode = "block" | "area" | "farm";

/**
 * One string property off a clicked feature.
 *
 * GeoJSON types a feature's properties as `any`, so every read of one is
 * unsafe. Naming that here keeps it to a single place, and the string check
 * is real: a source can carry a property of any type.
 */
function featureProp(properties: unknown, key: string): string | null {
  if (typeof properties !== "object" || properties === null) return null;
  const value = (properties as Record<string, unknown>)[key];
  return typeof value === "string" ? value : null;
}

function emptyCollection(): FeatureCollection {
  return { type: "FeatureCollection", features: [] };
}

function buildStyle(): StyleSpecification {
  return {
    version: 8,
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

function blockFeatures(
  blocks: MapBlock[],
  showAll: boolean,
  colorOf: (status: StatusCode) => string,
): FeatureCollection {
  return {
    type: "FeatureCollection",
    features: blocks.map(
      (block): Feature => ({
        type: "Feature",
        id: block.blockId,
        geometry: block.boundary,
        properties: {
          block_id: block.blockId,
          code: block.code,
          selected: block.selected,
          // Resolved here rather than in a paint expression: the colours are
          // the platform's own list, served by the API, and a `match` on
          // status codes in the style would be a second copy of it.
          color: block.status === null ? "#9aa0a6" : colorOf(block.status),
          // A block the tree never ran on is not grey-because-unassessed, it
          // is absent. It draws hollow so the two cannot be confused.
          didNotRun: block.status === null,
          // In the whole-farm view nothing is dimmed: the point of that view
          // is to compare the blocks, not to focus one.
          showAll: showAll,
        },
      }),
    ),
  };
}

function cellFeatures(cells: MapCell[]): FeatureCollection {
  return {
    type: "FeatureCollection",
    features: cells.map(
      (cell): Feature => ({
        type: "Feature",
        id: cell.cellId,
        geometry: { type: "Polygon", coordinates: [cell.ring] },
        properties: { cell_id: cell.cellId },
      }),
    ),
  };
}

function outlineFeatures(cells: MapCell[], highlighted: Set<string>): FeatureCollection {
  const chosen = cells.filter((cell) => highlighted.has(cell.cellId));
  const segments = outlineSegments(chosen);
  return {
    type: "FeatureCollection",
    features: segments.map(
      (segment): Feature => ({
        type: "Feature",
        geometry: { type: "LineString", coordinates: segment },
        properties: {},
      }),
    ),
  };
}

export function HealthMap({
  blocks,
  cells,
  highlighted,
  colorOf,
  onSelectBlock,
  onSelectCell,
  fitMode,
  fitKey,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MlMap | null>(null);
  // State, not a ref. A ref change does not re-run an effect, so gating the
  // data effects on one meant that whenever the queries resolved before the
  // map's load event they ran once against an unready map and never again.
  const [ready, setReady] = useState(false);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  // Handlers change on every render; the map keeps one reference and reads
  // the current one through this, so listeners are attached once.
  const handlers = useRef({ onSelectBlock, onSelectCell });
  handlers.current = { onSelectBlock, onSelectCell };

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: buildStyle(),
      center: [31.0, 30.5],
      zoom: 13,
      attributionControl: false,
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-left");
    map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");

    map.on("load", () => {
      map.addSource(BLOCK_SOURCE, { type: "geojson", data: emptyCollection() });
      map.addLayer({
        id: "fh-block-fill",
        type: "fill",
        source: BLOCK_SOURCE,
        paint: {
          "fill-color": ["get", "color"],
          // The block in focus reads at full strength and the rest are
          // dimmed, so the eye stays on it without losing the farm's shape.
          // A block the tree never ran on carries no fill at all.
          "fill-opacity": [
            "case",
            ["get", "didNotRun"],
            0,
            ["any", ["get", "selected"], ["get", "showAll"]],
            0.62,
            0.28,
          ],
        },
      });
      map.addLayer({
        id: "fh-block-line",
        type: "line",
        source: BLOCK_SOURCE,
        paint: {
          "line-color": ["case", ["get", "selected"], "#1f2420", "#e8e5db"],
          "line-width": ["case", ["get", "selected"], 2.5, 1],
        },
      });

      // A 1x1 transparent placeholder: an image source needs an image at
      // creation, and the real canvas is not painted until cells arrive.
      const blank = document.createElement("canvas");
      blank.width = 1;
      blank.height = 1;
      map.addSource(CELL_IMAGE_SOURCE, {
        type: "image",
        url: blank.toDataURL(),
        coordinates: [
          [0, 0],
          [0, 0],
          [0, 0],
          [0, 0],
        ],
      });
      map.addLayer({
        id: CELL_IMAGE_LAYER,
        type: "raster",
        source: CELL_IMAGE_SOURCE,
        // Hidden until a block with cell verdicts is chosen. The placeholder
        // image is 1x1 over a zero-area footprint, which must never be drawn.
        layout: { visibility: "none" },
        paint: { "raster-opacity": 0.85, "raster-resampling": "linear" },
      });

      map.addSource(CELL_HIT_SOURCE, { type: "geojson", data: emptyCollection() });
      map.addLayer({
        id: "fh-cell-hit",
        type: "fill",
        source: CELL_HIT_SOURCE,
        // Invisible but present: this is what a click lands on, so the
        // smoothing never moves a target.
        paint: { "fill-color": "#000000", "fill-opacity": 0 },
      });

      map.addSource(OUTLINE_SOURCE, { type: "geojson", data: emptyCollection() });
      map.addLayer({
        id: "fh-outline-halo",
        type: "line",
        source: OUTLINE_SOURCE,
        paint: { "line-color": "#ffffff", "line-width": 4, "line-opacity": 0.9 },
      });
      map.addLayer({
        id: "fh-outline",
        type: "line",
        source: OUTLINE_SOURCE,
        paint: { "line-color": "#1f2420", "line-width": 1.6 },
      });

      map.on("click", "fh-cell-hit", (event) => {
        const id = featureProp(event.features?.[0]?.properties, "cell_id");
        if (id !== null) handlers.current.onSelectCell(id);
      });
      map.on("click", "fh-block-fill", (event) => {
        const id = featureProp(event.features?.[0]?.properties, "block_id");
        if (id !== null) handlers.current.onSelectBlock(id);
      });
      for (const layer of ["fh-cell-hit", "fh-block-fill"]) {
        map.on("mouseenter", layer, () => {
          map.getCanvas().style.cursor = "pointer";
        });
        map.on("mouseleave", layer, () => {
          map.getCanvas().style.cursor = "";
        });
      }
      setReady(true);
      map.resize();
    });

    return () => {
      setReady(false);
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // Blocks
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    // eslint-disable-next-line @typescript-eslint/no-unnecessary-type-assertion -- tsc types getSource as the Source base, which has no setData/setCoordinates
    const source = map.getSource(BLOCK_SOURCE) as GeoJSONSource | undefined;
    source?.setData(blockFeatures(blocks, fitMode === "farm", colorOf));
  }, [blocks, fitMode, ready, colorOf]);

  // Cells: the blurred image, and the invisible polygons under it
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;

    // eslint-disable-next-line @typescript-eslint/no-unnecessary-type-assertion -- tsc types getSource as the Source base, which has no setData/setCoordinates
    const hit = map.getSource(CELL_HIT_SOURCE) as GeoJSONSource | undefined;
    hit?.setData(cellFeatures(cells));

    // eslint-disable-next-line @typescript-eslint/no-unnecessary-type-assertion -- tsc types getSource as the Source base, which has no setData/setCoordinates
    const image = map.getSource(CELL_IMAGE_SOURCE) as ImageSource | undefined;
    if (!image) return;

    const paintable: PaintCell[] = cells.map((cell) => ({
      cellId: cell.cellId,
      ring: cell.ring,
      status: cell.status,
    }));
    const box = cellsBbox(paintable);
    if (box === null) {
      // No cells: hide the layer. Collapsing the coordinates instead gives
      // MapLibre a zero-area quad, it divides by zero working out the tile
      // coordinates, and the page dies with "x=Infinity, y=Infinity,
      // z=Infinity outside of bounds". Every verdict on the reference farm
      // is block-scoped, so this is the normal path, not an edge case.
      map.setLayoutProperty(CELL_IMAGE_LAYER, "visibility", "none");
      return;
    }

    const size = canvasSize(box);
    const canvas = canvasRef.current ?? document.createElement("canvas");
    canvasRef.current = canvas;
    canvas.width = size.width;
    canvas.height = size.height;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    paintCells(ctx, paintable, box, colorOf, blurRadius(cells.length, size));

    // updateImage keeps the source; setCoordinates moves it. Both are needed
    // because the block changes as often as the colours do.
    image.updateImage({ url: canvas.toDataURL() });
    image.setCoordinates(bboxToImageCoordinates(box));
    map.setLayoutProperty(CELL_IMAGE_LAYER, "visibility", "visible");
  }, [cells, colorOf, ready]);

  // The selected area's outline
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    // eslint-disable-next-line @typescript-eslint/no-unnecessary-type-assertion -- tsc types getSource as the Source base, which has no setData/setCoordinates
    const source = map.getSource(OUTLINE_SOURCE) as GeoJSONSource | undefined;
    source?.setData(outlineFeatures(cells, highlighted));
  }, [cells, highlighted, ready]);

  // Framing. Three answers, one effect, so they cannot disagree about
  // padding or duration.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;

    let box = null;
    if (fitMode === "farm") {
      box = farmBounds(blocks.map((block) => block.boundary));
    } else if (fitMode === "area") {
      const chosen = cells.filter((cell) => highlighted.has(cell.cellId));
      box = areaBounds(chosen.map((cell) => cell.ring));
      // An area with no cells is not a reason to sit on the last frame.
      if (box === null) box = boundsOfPolygon(blocks.find((b) => b.selected)?.boundary);
    } else {
      box = boundsOfPolygon(blocks.find((block) => block.selected)?.boundary);
    }
    if (box === null) return;

    map.fitBounds(toLngLatBounds(padBounds(box, 0.08)), { padding: 40, duration: 450 });
    // `highlighted` is deliberately not a dependency: hovering a chip
    // previews an area on the map and must not fly the camera to it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fitKey, fitMode, blocks, cells, ready]);

  return <div ref={containerRef} className="h-full w-full" data-testid="health-map" />;
}

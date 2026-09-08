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

import { useEffect, useRef } from "react";
import maplibregl, {
  type GeoJSONSource,
  type ImageSource,
  type Map as MlMap,
  type StyleSpecification,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Feature, FeatureCollection, Polygon } from "geojson";

import type { StatusCode } from "@/api/farmHealth";
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
const CELL_HIT_SOURCE = "fh-cell-hit";
const OUTLINE_SOURCE = "fh-outline";

/** A block outline, and whether it is the one in focus. */
export interface MapBlock {
  blockId: string;
  code: string;
  boundary: Polygon;
  selected: boolean;
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
  /** Changing this refits the map. Pass the selected block id. */
  fitKey: string;
}

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

function blockFeatures(blocks: MapBlock[]): FeatureCollection {
  return {
    type: "FeatureCollection",
    features: blocks.map(
      (block): Feature => ({
        type: "Feature",
        id: block.blockId,
        geometry: block.boundary,
        properties: { block_id: block.blockId, code: block.code, selected: block.selected },
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
  fitKey,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MlMap | null>(null);
  const readyRef = useRef(false);
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
          // The unselected blocks are greyed so the eye stays on the one in
          // focus. Mohamed asked for that on 2026-09-07.
          "fill-color": "#5f675c",
          "fill-opacity": ["case", ["get", "selected"], 0, 0.45],
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
        id: "fh-cell-image",
        type: "raster",
        source: CELL_IMAGE_SOURCE,
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
      readyRef.current = true;
      map.resize();
    });

    return () => {
      readyRef.current = false;
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // Blocks
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !readyRef.current) return;
    // eslint-disable-next-line @typescript-eslint/no-unnecessary-type-assertion -- tsc types getSource as the Source base, which has no setData/setCoordinates
    const source = map.getSource(BLOCK_SOURCE) as GeoJSONSource | undefined;
    source?.setData(blockFeatures(blocks));
  }, [blocks]);

  // Cells: the blurred image, and the invisible polygons under it
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !readyRef.current) return;

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
      // No cells: collapse the image rather than leave the last block's
      // colours pinned over a block that has none.
      image.setCoordinates([
        [0, 0],
        [0, 0],
        [0, 0],
        [0, 0],
      ]);
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
  }, [cells, colorOf]);

  // The selected area's outline
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !readyRef.current) return;
    // eslint-disable-next-line @typescript-eslint/no-unnecessary-type-assertion -- tsc types getSource as the Source base, which has no setData/setCoordinates
    const source = map.getSource(OUTLINE_SOURCE) as GeoJSONSource | undefined;
    source?.setData(outlineFeatures(cells, highlighted));
  }, [cells, highlighted]);

  // Frame the selected block
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !readyRef.current) return;
    const selected = blocks.find((block) => block.selected);
    const ring = selected?.boundary.coordinates[0];
    if (!ring || ring.length === 0) return;
    const bounds = new maplibregl.LngLatBounds(
      ring[0] as [number, number],
      ring[0] as [number, number],
    );
    for (const point of ring) bounds.extend(point as [number, number]);
    map.fitBounds(bounds, { padding: 48, duration: 450 });
  }, [fitKey, blocks]);

  return <div ref={containerRef} className="h-full w-full" data-testid="health-map" />;
}

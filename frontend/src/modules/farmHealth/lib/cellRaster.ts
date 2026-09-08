// Painting a block's grid cells as one smooth image.
//
// The prototype smoothed the grid with an SVG blur filter. MapLibre has no
// equivalent for a fill layer, so the cells are drawn into a canvas, blurred
// there, and handed to the map as an `image` source pinned to the block's
// bounding box. The colours are the image; a separate transparent fill layer
// over the real cell polygons keeps clicks and hover exact.
//
// Why blur at all: a 121-cell grid drawn as flat squares reads as pixel art,
// and Mohamed asked on 2026-09-07 for the colours to meet in curves. It
// changes no value and no click target.

import type { StatusCode } from "@/api/farmHealth";

/** A cell to paint: its polygon ring and the status it holds. */
export interface PaintCell {
  cellId: string;
  /** Outer ring, [lon, lat] pairs, as GeoJSON gives it. */
  ring: [number, number][];
  status: StatusCode;
}

/** West, south, east, north. The image source's footprint. */
export interface Bbox {
  west: number;
  south: number;
  east: number;
  north: number;
}

/** The four corners MapLibre wants, clockwise from the top left. */
export type ImageCoordinates = [
  [number, number],
  [number, number],
  [number, number],
  [number, number],
];

/**
 * The bounding box of every cell, with a margin.
 *
 * The margin matters: the blur spreads colour outward, and a box drawn
 * tight to the cells clips that spread into a hard straight edge along the
 * block's border — the exact artefact the blur exists to remove.
 */
export function cellsBbox(cells: PaintCell[], marginFraction = 0.04): Bbox | null {
  if (cells.length === 0) return null;
  let west = Infinity;
  let south = Infinity;
  let east = -Infinity;
  let north = -Infinity;
  for (const cell of cells) {
    for (const [lon, lat] of cell.ring) {
      if (lon < west) west = lon;
      if (lon > east) east = lon;
      if (lat < south) south = lat;
      if (lat > north) north = lat;
    }
  }
  if (!Number.isFinite(west) || !Number.isFinite(south)) return null;
  const mx = (east - west) * marginFraction;
  const my = (north - south) * marginFraction;
  return { west: west - mx, south: south - my, east: east + mx, north: north + my };
}

export function bboxToImageCoordinates(box: Bbox): ImageCoordinates {
  return [
    [box.west, box.north],
    [box.east, box.north],
    [box.east, box.south],
    [box.west, box.south],
  ];
}

/**
 * How many pixels to give the canvas.
 *
 * Proportional to the box so the cells stay square, and capped: past about
 * 1024 the blur costs more than it shows, and a 121-cell grid is 11 cells
 * across, so each cell still gets tens of pixels.
 */
export function canvasSize(box: Bbox, max = 1024): { width: number; height: number } {
  const w = box.east - box.west;
  const h = box.north - box.south;
  if (w <= 0 || h <= 0) return { width: max, height: max };
  const scale = max / Math.max(w, h);
  return {
    width: Math.max(1, Math.round(w * scale)),
    height: Math.max(1, Math.round(h * scale)),
  };
}

/**
 * The blur radius, in canvas pixels.
 *
 * Tied to the cell size rather than fixed: a block of 64 cells and one of
 * 400 must look equally smooth, and a constant radius would turn the second
 * into a single wash of colour. 0.4 of a cell is what the prototype settled
 * on after Mohamed found 0.28 still stepped.
 */
export function blurRadius(cellCount: number, size: { width: number; height: number }): number {
  const across = Math.max(1, Math.sqrt(Math.max(1, cellCount)));
  const cellPixels = Math.max(size.width, size.height) / across;
  return Math.max(2, Math.round(cellPixels * 0.4));
}

/** The 2D context calls this module needs. Narrow so a test can fake it. */
export interface PaintContext {
  canvas: { width: number; height: number };
  filter: string;
  // Widened to what a real 2D context declares. This module only ever
  // assigns a colour string; accepting the union is what lets a
  // CanvasRenderingContext2D be passed without a cast at the call site.
  fillStyle: string | CanvasGradient | CanvasPattern;
  clearRect(x: number, y: number, w: number, h: number): void;
  beginPath(): void;
  moveTo(x: number, y: number): void;
  lineTo(x: number, y: number): void;
  closePath(): void;
  fill(): void;
}

/**
 * Draw every cell into the canvas, blurred.
 *
 * The blur is set once, on the context, so the shapes composite through it
 * together. Blurring each cell on its own would leave a seam wherever two
 * cells of the same colour meet, which looks worse than the grid it
 * replaced.
 */
export function paintCells(
  ctx: PaintContext,
  cells: PaintCell[],
  box: Bbox,
  colorOf: (status: StatusCode) => string,
  radius: number,
): void {
  const { width, height } = ctx.canvas;
  ctx.clearRect(0, 0, width, height);
  const spanX = box.east - box.west;
  const spanY = box.north - box.south;
  if (spanX <= 0 || spanY <= 0) return;

  ctx.filter = radius > 0 ? `blur(${radius}px)` : "none";
  for (const cell of cells) {
    if (cell.ring.length < 3) continue;
    ctx.fillStyle = colorOf(cell.status);
    ctx.beginPath();
    cell.ring.forEach(([lon, lat], index) => {
      const x = ((lon - box.west) / spanX) * width;
      // Latitude grows north, canvas y grows down.
      const y = ((box.north - lat) / spanY) * height;
      if (index === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.closePath();
    ctx.fill();
  }
  ctx.filter = "none";
}

/**
 * The outline of a set of cells: only the edges with no neighbour inside it.
 *
 * Drawing every cell's own outline would put the grid back on top of the
 * image the blur just removed. This traces the shape instead.
 *
 * Neighbours are decided by row and column, not by geometry: a rezone can
 * leave cells that do not quite touch, and a geometric test would then open
 * the outline along an invisible hairline.
 */
export interface OutlineCell {
  row: number;
  col: number;
  ring: [number, number][];
}

export function outlineSegments(cells: OutlineCell[]): [number, number][][] {
  const present = new Set(cells.map((c) => `${c.row}:${c.col}`));
  const segments: [number, number][][] = [];
  for (const cell of cells) {
    // A cell ring is a closed box; take its extent rather than trusting the
    // winding order, which differs between PostGIS and hand-built fixtures.
    let west = Infinity;
    let south = Infinity;
    let east = -Infinity;
    let north = -Infinity;
    for (const [lon, lat] of cell.ring) {
      if (lon < west) west = lon;
      if (lon > east) east = lon;
      if (lat < south) south = lat;
      if (lat > north) north = lat;
    }
    if (!Number.isFinite(west)) continue;
    const nw: [number, number] = [west, north];
    const ne: [number, number] = [east, north];
    const se: [number, number] = [east, south];
    const sw: [number, number] = [west, south];
    if (!present.has(`${cell.row - 1}:${cell.col}`)) segments.push([nw, ne]);
    if (!present.has(`${cell.row + 1}:${cell.col}`)) segments.push([sw, se]);
    if (!present.has(`${cell.row}:${cell.col - 1}`)) segments.push([nw, sw]);
    if (!present.has(`${cell.row}:${cell.col + 1}`)) segments.push([ne, se]);
  }
  return segments;
}

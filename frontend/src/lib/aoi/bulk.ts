// Bulk AOI upload helpers for the Farm Console "Upload AOI files…" flow.
//
// Turns a multi-file drop into editable review rows (one block per polygon),
// derives a block code from each filename, and classifies each row against
// the farm's existing blocks so the review table + map preview can show —
// before commit — which uploads create, match, or replace a block. The
// backend reconcile (/farms/{id}/blocks:bulk) is authoritative; this is a
// best-effort preview.
import type { Polygon } from "geojson";

import { AoiParseError, parseAoiFile, pickPolygonalFeatures } from "./parse";

/** Client-side reconcile status for the preview (mirrors the map legend). */
export type BulkRowStatus = "new" | "reuse" | "replace" | "error";

export interface BulkRow {
  // Stable client id (for React keys + selection). Not sent to the server.
  id: string;
  fileName: string;
  // Editable in the review table; derived from the filename by default.
  code: string;
  name: string;
  // null only when the file/feature could not be parsed into a Polygon.
  geometry: Polygon | null;
  // Set when parsing failed for this row; an i18n suffix under aoi.bulk.err.*.
  clientError: string | null;
}

// Block code charset accepted by the backend: [A-Za-z0-9][A-Za-z0-9_-]{0,31}.
const CODE_MAX = 32;

/**
 * Derive a block code from a filename: drop the extension, replace runs of
 * disallowed characters with a single dash, trim leading/trailing dashes, and
 * clamp to 32 chars. Falls back to "BLOCK" when nothing usable remains.
 */
export function filenameToCode(fileName: string): string {
  const base = fileName.replace(/\.[^.]+$/, "").split(/[\\/]/).pop() ?? fileName;
  const code = base
    .replace(/[^A-Za-z0-9_-]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^[-_]+|[-_]+$/g, "")
    .slice(0, CODE_MAX);
  return code.length > 0 ? code : "BLOCK";
}

function errorCodeFor(err: unknown): string {
  if (err instanceof AoiParseError) {
    if (err.code === "too_large") return "tooLarge";
    if (err.code === "unsupported_extension") return "unsupported";
    if (err.code === "empty") return "empty";
    return "invalid";
  }
  return "invalid";
}

let _seq = 0;
function nextId(): string {
  _seq += 1;
  return `bulk-${_seq}`;
}

/** Flatten a picked feature's geometry into one or more plain Polygons. */
function polygonsOf(geom: Polygon | GeoJSON.MultiPolygon): Polygon[] {
  if (geom.type === "Polygon") return [geom];
  return geom.coordinates.map((coordinates) => ({ type: "Polygon", coordinates }));
}

/**
 * Parse a list of dropped files into review rows. One block per polygon: a
 * file yielding a single polygon gets the filename code; a file yielding N
 * polygons expands to N rows with `-1, -2, …` suffixes. Files that fail to
 * parse (or contain no polygon) become a single error row.
 */
export async function deriveRowsFromFiles(files: File[]): Promise<BulkRow[]> {
  const rows: BulkRow[] = [];
  for (const file of files) {
    const baseCode = filenameToCode(file.name);
    try {
      const parsed = await parseAoiFile(file);
      const polys = pickPolygonalFeatures(parsed.collection).flatMap((f) => polygonsOf(f.geometry));
      if (polys.length === 0) {
        rows.push({ id: nextId(), fileName: file.name, code: baseCode, name: "", geometry: null, clientError: "empty" });
        continue;
      }
      polys.forEach((geometry, i) => {
        const code = polys.length === 1 ? baseCode : `${baseCode}-${i + 1}`.slice(0, CODE_MAX);
        rows.push({ id: nextId(), fileName: file.name, code, name: "", geometry, clientError: null });
      });
    } catch (err) {
      rows.push({
        id: nextId(),
        fileName: file.name,
        code: baseCode,
        name: "",
        geometry: null,
        clientError: errorCodeFor(err),
      });
    }
  }
  return rows;
}

/** Normalized geometry key for approximate equality (6 dp, order-sensitive). */
function geomKey(geom: Polygon): string {
  const round = (n: number): number => Math.round(n * 1e6) / 1e6;
  return JSON.stringify(geom.coordinates.map((ring) => ring.map(([x, y]) => [round(x), round(y)])));
}

export interface ExistingBlock {
  code: string;
  geometry: Polygon;
}

export interface ClassifiedRow extends BulkRow {
  status: BulkRowStatus;
  // The existing block this row matches by code (for reuse/replace), if any.
  existingCode: string | null;
}

/**
 * Classify each row against existing blocks + the rest of the batch.
 *
 * Rules mirror the backend: a parse error or a duplicate code within the
 * upload → "error"; a code that matches no existing block → "new"; a code
 * that matches an existing block with an identical boundary → "reuse"; a
 * code that matches an existing block with a changed boundary → "replace".
 */
export function classifyRows(rows: BulkRow[], existing: ExistingBlock[]): ClassifiedRow[] {
  const existingByCode = new Map<string, string>(); // code -> geomKey
  for (const b of existing) existingByCode.set(b.code, geomKey(b.geometry));

  const seen = new Set<string>();
  return rows.map((row) => {
    if (row.clientError || !row.geometry) {
      return { ...row, status: "error" as const, existingCode: null };
    }
    if (seen.has(row.code)) {
      return { ...row, status: "error" as const, existingCode: null, clientError: "duplicate" };
    }
    seen.add(row.code);

    const existingKey = existingByCode.get(row.code);
    if (existingKey === undefined) {
      return { ...row, status: "new" as const, existingCode: null };
    }
    const status: BulkRowStatus = existingKey === geomKey(row.geometry) ? "reuse" : "replace";
    return { ...row, status, existingCode: row.code };
  });
}

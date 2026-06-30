// Readable label for a sub-block grid cell (per-cell P2). Returns null for
// block-scoped rows (no cell). Grid cells are addressed by global row/col
// indices; "R{row}·C{col}" is compact and stable across the app.
export function cellLabel(
  row: number | null | undefined,
  col: number | null | undefined,
): string | null {
  if (row == null || col == null) return null;
  return `R${row}·C${col}`;
}

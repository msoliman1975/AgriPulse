// Is the cell mesh drawn from the day the strip is parked on?
//
// `GET /farms/{id}/grid-cells?at=` answers with the newest cell reading AT OR
// BEFORE the selected instant. A day with no cell rows therefore comes back
// holding an OLDER day's numbers. They are real numbers, they render normally,
// and nothing on the map says they belong to a different day.
//
// That is not a rare edge. Cell values are written by a backfill that replays
// scenes oldest-first over hours, so a farm mid-backfill has rasters for every
// day and cell values only for the early ones. Mohamed hit exactly this: every
// cell on every date he picked read "as of Jul 23", because Jul 23 was as far
// as the backfill had reached.
//
// Kept out of the hook so the rule can be tested on plain values.

export interface CellDateGap {
  /** UTC day the newest drawn cell reading was acquired. */
  drawn: string;
  /** The day the strip is parked on. */
  wanted: string;
  /** Distinct days across the drawn cells. More than one means blocks disagree. */
  dayCount: number;
}

/** A scene, narrowed to the two fields this rule reads. */
export interface SceneDay {
  scene_date: string;
  /**
   * Blocks whose index rasters exist for this pass. Zero means the day draws
   * nothing, so it is not the day the map is failing to show.
   */
  computed_count: number;
}

/**
 * The UTC day of an acquisition instant.
 *
 * UTC, not local: `time` is an instant, and taking its local day puts every
 * morning pass a day early west of Greenwich. That is the same fault that
 * mislabelled the whole scene strip in #494.
 */
function utcDay(iso: string): string | null {
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return null;
  return new Date(ms).toISOString().slice(0, 10);
}

/**
 * The newest day that can actually be drawn.
 *
 * Used only when no day is selected, where the strip means "latest". Days with
 * no computed raster are skipped: the map never claimed to be showing them, so
 * naming one as the day the reader wanted would be a false alarm on any farm
 * whose most recent pass was lost to cloud.
 */
function newestDrawableDay(scenes: readonly SceneDay[]): string | null {
  let newest: string | null = null;
  for (const s of scenes) {
    if (s.computed_count <= 0) continue;
    if (newest === null || s.scene_date > newest) newest = s.scene_date;
  }
  return newest;
}

/**
 * The gap to warn about, or null when the mesh is on the right day.
 *
 * `cellTimes` is the `time` of every drawn cell. Cells with no reading are the
 * caller's to filter out — a cell the pass did not cover carries no day and
 * must not vote on which day is drawn.
 */
export function cellDateGap(args: {
  cellTimes: readonly (string | null)[];
  sceneDate: string | null;
  scenes: readonly SceneDay[];
}): CellDateGap | null {
  const days = new Set<string>();
  for (const iso of args.cellTimes) {
    if (!iso) continue;
    const day = utcDay(iso);
    if (day) days.add(day);
  }
  // No readings at all is a different message, and GridCellPopup already
  // carries it. Saying "these cells are from another day" about cells that
  // hold no value would name a day the reader cannot see anywhere.
  if (days.size === 0) return null;

  const sorted = [...days].sort();
  const drawn = sorted[sorted.length - 1];
  const wanted = args.sceneDate ?? newestDrawableDay(args.scenes);
  if (!wanted || wanted === drawn) return null;

  return { drawn, wanted, dayCount: days.size };
}

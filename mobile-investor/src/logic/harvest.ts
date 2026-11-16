/** Pure helpers for the Harvest tab (investor app v2, PR 9). */
import type { HarvestPick } from "@/api/client";

/** Bar heights, 0-100, against the heaviest pick; at least 6 so a bar shows. */
export function barHeights(picks: HarvestPick[]): number[] {
  const weights = picks.map((p) => Number(p.weight_kg));
  const max = Math.max(0, ...weights);
  if (max <= 0) return weights.map(() => 6);
  return weights.map((w) => Math.max(6, (w / max) * 100));
}

/** Oldest pick first, as they happened; ties by pick number. */
export function inPickOrder(picks: HarvestPick[]): HarvestPick[] {
  return [...picks].sort(
    (a, b) => a.harvested_on.localeCompare(b.harvested_on) || a.pick_no - b.pick_no,
  );
}

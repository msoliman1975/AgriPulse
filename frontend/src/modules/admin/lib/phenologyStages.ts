// Pure rules for a crop's stage calendar.
//
// Split from the editor component so React Fast Refresh keeps working, and so
// the rules can be tested without rendering anything. They mirror the
// validators in backend/app/modules/farms/phenology.py — the point is that an
// author is told which stage is wrong before saving, rather than getting a 422
// about the payload as a whole.

import { ANNUAL_ADVANCE_MODES, PERENNIAL_ADVANCE_MODES } from "@/api/cropCatalog";
import type { AdvanceRule, Crop, PhenologyStage } from "@/api/crops";

const CODE_RE = /^[a-z0-9][a-z0-9_]*$/;
const MMDD_RE = /^(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$/;

export function defaultAdvance(mode: AdvanceRule["mode"]): AdvanceRule {
  switch (mode) {
    case "calendar_doy":
      return { mode, start_doy: "01-01", end_doy: "12-31" };
    case "days_from_planting":
      return { mode, start_day: 0, end_day: 30 };
    case "gdd_from_planting":
      return { mode, start_gdd: 0, end_gdd: 500 };
    default:
      return { mode: "manual" };
  }
}

/** Everything wrong with the calendar, in the author's words. Mirrors the
 *  backend validators so a save is refused here first, with the offending
 *  stage named rather than a 422 about the payload as a whole. */
export function validateStages(stages: PhenologyStage[], crop: Crop): string[] {
  const problems: string[] = [];
  const allowed: readonly string[] = crop.is_perennial
    ? PERENNIAL_ADVANCE_MODES
    : ANNUAL_ADVANCE_MODES;
  const seen = new Set<string>();
  for (const stage of stages) {
    const name = stage.code || "(unnamed)";
    if (!CODE_RE.test(stage.code)) problems.push(`${name}: code must be lower_snake_case`);
    if (seen.has(stage.code)) problems.push(`${name}: duplicate code`);
    seen.add(stage.code);
    if (!stage.name_en.trim()) problems.push(`${name}: English name is required`);
    if (!stage.name_ar.trim()) problems.push(`${name}: Arabic name is required`);
    if (!allowed.includes(stage.advance.mode)) {
      problems.push(
        `${name}: ${stage.advance.mode} is not allowed for ${
          crop.is_perennial ? "a perennial" : "an annual"
        } crop`,
      );
      continue;
    }
    const a = stage.advance;
    if (a.mode === "calendar_doy") {
      // Wrap-around (12-01 → 01-31) is legal, so only the format is checked.
      if (!MMDD_RE.test(a.start_doy) || !MMDD_RE.test(a.end_doy)) {
        problems.push(`${name}: dates must be MM-DD`);
      }
    } else if (a.mode === "days_from_planting") {
      if (a.end_day <= a.start_day) problems.push(`${name}: end day must be after start day`);
    } else if (a.mode === "gdd_from_planting") {
      if (a.end_gdd <= a.start_gdd) problems.push(`${name}: end GDD must be above start GDD`);
      if (!crop.gdd_base_temp_c) {
        problems.push(`${name}: needs the crop to set a GDD base temperature first`);
      }
    }
  }
  if (stages.length === 0) problems.push("A calendar needs at least one stage.");
  return problems;
}

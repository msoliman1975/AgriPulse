// Form state for the catalogue's heat-unit settings (decision D17).
//
// Mirrors the CHECKs in backend public migration 0112: a start value only with
// a kind, MM-DD for a calendar date, a stage code for a stage, none for
// planting.

import type { GddMethod, GddStartKind, HeatUnitSettings } from "@/api/crops";

const MMDD_RE = /^(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$/;

export interface HeatUnitDraft {
  method: GddMethod | "";
  startKind: GddStartKind | "";
  startValue: string;
}

export function heatUnitDraft(node: HeatUnitSettings): HeatUnitDraft {
  return {
    method: node.gdd_method ?? "",
    startKind: node.gdd_start_kind ?? "",
    startValue: node.gdd_start_value ?? "",
  };
}

/** The PATCH fields for a draft. Empty selects clear the level (inherit). */
export function heatUnitPatch(draft: HeatUnitDraft): Required<HeatUnitSettings> {
  const kind = draft.startKind || null;
  const value = kind === null || kind === "planting" ? null : draft.startValue.trim() || null;
  return {
    gdd_method: draft.method || null,
    gdd_start_kind: kind,
    gdd_start_value: value,
  };
}

/** The i18n key of what is wrong with the start, or null when it can be saved. */
export function heatUnitStartError(draft: HeatUnitDraft): string | null {
  const value = draft.startValue.trim();
  if (draft.startKind === "date" && !MMDD_RE.test(value)) return "heatUnits.errorDate";
  if (draft.startKind === "stage" && !value) return "heatUnits.errorStage";
  return null;
}

// Shared presentation helpers for operation manuals.

import type { PhenologyStage } from "@/api/agriOperation";
import { localizedField } from "@/lib/localizedField";

export const TYPE_CLASS: Record<string, string> = {
  planting: "bg-ap-primary-soft text-ap-plant",
  fertilizing: "bg-blue-50 text-ap-fert",
  spraying: "bg-purple-50 text-ap-spray",
  pruning: "bg-ap-warn-soft text-ap-prune",
  harvesting: "bg-ap-crit-soft text-ap-harv",
  irrigation: "bg-cyan-50 text-ap-irrig",
  soil_prep: "bg-amber-50 text-amber-800",
  observation: "bg-ap-line/70 text-ap-muted",
  pollination: "bg-purple-50 text-ap-spray",
  growth_regulator: "bg-lime-50 text-lime-800",
  thinning: "bg-teal-50 text-teal-800",
  bagging: "bg-amber-50 text-amber-800",
  hilling: "bg-amber-50 text-amber-800",
  bending: "bg-amber-50 text-amber-800",
  trap_service: "bg-ap-crit-soft text-ap-harv",
};

export function stageName(stage: PhenologyStage, lang: string): string {
  return localizedField(lang, stage.name_en ?? stage.code, stage.name_ar) ?? stage.code;
}

// Stage colours cycle through the app's stage tokens in phenological order.
export const STAGE_COLORS = [
  "bg-ap-stage-post",
  "bg-ap-stage-flow",
  "bg-ap-stage-frset",
  "bg-ap-stage-frdev",
  "bg-ap-stage-ripen",
  "bg-ap-stage-harv",
  "bg-ap-primary-soft",
  "bg-ap-warn-soft",
  "bg-ap-crit-soft",
];

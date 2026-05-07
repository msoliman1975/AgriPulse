import { differenceInDays, format, formatDistanceToNow, parseISO } from "date-fns";

import type { ActivityType } from "@/api/plans";

export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = parseISO(iso);
  const days = differenceInDays(new Date(), d);
  if (Math.abs(days) > 60) return format(d, "MMM d, yyyy");
  return formatDistanceToNow(d, { addSuffix: true });
}

export function formatDateShort(iso: string | null | undefined): string {
  if (!iso) return "—";
  return format(parseISO(iso), "MMM d");
}

export function formatPercent(value: number, signed = false): string {
  const sign = signed && value > 0 ? "+" : "";
  return `${sign}${(value * 100).toFixed(1)}%`;
}

const TYPE_LABEL: Record<ActivityType, string> = {
  planting: "Planting",
  fertilizing: "Fertilizing",
  spraying: "Spraying",
  pruning: "Pruning",
  harvesting: "Harvesting",
  irrigation: "Irrigation",
  soil_prep: "Soil prep",
  observation: "Observation",
};

export function activityTypeLabel(t: ActivityType): string {
  return TYPE_LABEL[t] ?? t;
}

const TYPE_BG: Record<ActivityType, string> = {
  planting: "bg-ap-plant",
  fertilizing: "bg-ap-fert",
  spraying: "bg-ap-spray",
  pruning: "bg-ap-prune",
  harvesting: "bg-ap-harv",
  irrigation: "bg-ap-irrig",
  soil_prep: "bg-amber-500",
  observation: "bg-slate-400",
};

export function activityTypeBgClass(t: ActivityType): string {
  return TYPE_BG[t] ?? "bg-slate-400";
}

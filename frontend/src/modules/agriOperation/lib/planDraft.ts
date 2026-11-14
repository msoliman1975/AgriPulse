// The Plan tab's working copy of a saved plan, and its conversion to and from
// the API shape. Pure, so the wizard's rules are tested without a browser.

import type {
  AllocationActivityEdit,
  AllocationCustomActivity,
  AllocationWriteRequest,
  SavedPlan,
  StartMode,
} from "@/api/agriOperation";

export interface PlanDraft {
  /** Set when editing an existing saved plan. */
  id: string | null;
  templateId: string;
  seasonLabel: string;
  seasonYear: number;
  startMode: StartMode;
  /** Selected blocks in pick order. */
  blockIds: string[];
  sameDate: string;
  perBlockDates: Record<string, string>;
  excludedCodes: string[];
  edits: Record<string, AllocationActivityEdit>;
  customs: AllocationCustomActivity[];
  overrides: Record<string, Record<string, string>>;
}

export function emptyDraft(templateId: string, today: Date = new Date()): PlanDraft {
  const year = today.getFullYear();
  return {
    id: null,
    templateId,
    seasonLabel: `Main season ${year}`,
    seasonYear: year,
    startMode: "same",
    blockIds: [],
    sameDate: today.toISOString().slice(0, 10),
    perBlockDates: {},
    excludedCodes: [],
    edits: {},
    customs: [],
    overrides: {},
  };
}

export function draftFromSaved(plan: SavedPlan): PlanDraft {
  const firstDate = plan.blocks[0]?.start_date ?? new Date().toISOString().slice(0, 10);
  return {
    id: plan.id,
    templateId: plan.template_id,
    seasonLabel: plan.season_label,
    seasonYear: plan.season_year,
    startMode: plan.start_mode,
    blockIds: plan.blocks.map((b) => b.block_id),
    sameDate: firstDate,
    perBlockDates: Object.fromEntries(plan.blocks.map((b) => [b.block_id, b.start_date])),
    excludedCodes: [...plan.excluded_codes],
    edits: { ...plan.activity_edits },
    customs: plan.custom_activities.map((c) => ({ ...c })),
    overrides: Object.fromEntries(
      Object.entries(plan.date_overrides).map(([k, v]) => [k, { ...v }]),
    ),
  };
}

export function startDateFor(draft: PlanDraft, blockId: string): string | null {
  const d = draft.startMode === "same" ? draft.sameDate : draft.perBlockDates[blockId];
  return d ? d : null;
}

/** What's missing before the plan can be previewed or saved, as i18n keys. */
export function draftProblems(draft: PlanDraft): string[] {
  const problems: string[] = [];
  if (draft.blockIds.length === 0) problems.push("plan.err.noBlocks");
  if (!draft.seasonLabel.trim()) problems.push("plan.err.noSeason");
  if (draft.blockIds.some((id) => !startDateFor(draft, id))) problems.push("plan.err.noDate");
  return problems;
}

export function toRequest(draft: PlanDraft): AllocationWriteRequest {
  // Drop overrides for blocks no longer in the plan.
  const overrides = Object.fromEntries(
    Object.entries(draft.overrides).filter(
      ([blockId, keys]) => draft.blockIds.includes(blockId) && Object.keys(keys).length > 0,
    ),
  );
  return {
    template_id: draft.templateId,
    season_label: draft.seasonLabel.trim(),
    season_year: draft.seasonYear,
    start_mode: draft.startMode,
    blocks: draft.blockIds.map((id) => ({
      block_id: id,
      start_date: startDateFor(draft, id) ?? "",
    })),
    excluded_codes: draft.excludedCodes,
    activity_edits: draft.edits,
    custom_activities: draft.customs,
    date_overrides: overrides,
  };
}

export function toggleCode(draft: PlanDraft, code: string): PlanDraft {
  const excluded = draft.excludedCodes.includes(code)
    ? draft.excludedCodes.filter((c) => c !== code)
    : [...draft.excludedCodes, code];
  return { ...draft, excludedCodes: excluded };
}

export function setOverride(
  draft: PlanDraft,
  blockId: string,
  key: string,
  date: string | null,
): PlanDraft {
  const forBlock = { ...(draft.overrides[blockId] ?? {}) };
  if (date) forBlock[key] = date;
  else delete forBlock[key];
  return { ...draft, overrides: { ...draft.overrides, [blockId]: forBlock } };
}

export function newCustomKey(): string {
  const rand =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID().replace(/-/g, "").slice(0, 12)
      : Math.random().toString(36).slice(2, 14);
  return `custom:${rand}`;
}

export function addDays(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

export function daysBetween(fromIso: string, toIso: string): number {
  return Math.round(
    (Date.parse(`${toIso}T00:00:00Z`) - Date.parse(`${fromIso}T00:00:00Z`)) / 86_400_000,
  );
}

import { differenceInCalendarDays, parseISO } from "date-fns";

import type { ActivityType, PlanActivity } from "@/api/plans";

export type ConflictRuleId = "CFL-SPRAY-WASH" | "CFL-PHI" | "CFL-PRUNE-FLOWER";

export interface ConflictEdge {
  ruleId: ConflictRuleId;
  message: string;
  activityIds: [string, string];
}

const SPRAY_WASH_WINDOW_DAYS = 3;

/**
 * Detect known activity conflicts on the same lane (= same block).
 *
 * MVP rules — see UX_SPEC.md §6.5:
 *   - CFL-SPRAY-WASH: spray + irrigation/fertigation pulse within 3 days
 *   - CFL-PHI: spray within pre-harvest interval days of harvest (skipped
 *     until product PHI metadata is available; placeholder kept so the
 *     UI's call-site is stable)
 *   - CFL-PRUNE-FLOWER: pruning during a flowering stage segment (skipped
 *     until growth_stage_logs flow into the rule call-site)
 */
export function detectConflicts(activities: ReadonlyArray<PlanActivity>): ConflictEdge[] {
  const out: ConflictEdge[] = [];
  const byBlock = new Map<string, PlanActivity[]>();
  for (const a of activities) {
    if (a.status === "skipped") continue;
    const list = byBlock.get(a.block_id) ?? [];
    list.push(a);
    byBlock.set(a.block_id, list);
  }

  for (const list of byBlock.values()) {
    for (let i = 0; i < list.length; i += 1) {
      for (let j = i + 1; j < list.length; j += 1) {
        const a = list[i];
        const b = list[j];
        const sprayWash = sprayWashConflict(a, b);
        if (sprayWash) {
          out.push(sprayWash);
        }
      }
    }
  }
  return out;
}

function sprayWashConflict(
  a: PlanActivity,
  b: PlanActivity,
): ConflictEdge | null {
  const aIsSpray = a.activity_type === "spraying";
  const bIsSpray = b.activity_type === "spraying";
  const aIsWater = isWateringType(a.activity_type);
  const bIsWater = isWateringType(b.activity_type);
  const sprayActivity = aIsSpray ? a : bIsSpray ? b : null;
  const waterActivity = aIsWater && !aIsSpray ? a : bIsWater && !bIsSpray ? b : null;
  if (!sprayActivity || !waterActivity) return null;

  const dAStart = parseISO(sprayActivity.scheduled_date);
  const dBStart = parseISO(waterActivity.scheduled_date);
  const distance = Math.abs(differenceInCalendarDays(dAStart, dBStart));
  if (distance > SPRAY_WASH_WINDOW_DAYS) return null;

  return {
    ruleId: "CFL-SPRAY-WASH",
    message:
      "Run irrigation AFTER spray dries (~14:00) to avoid washing product.",
    activityIds: [a.id, b.id],
  };
}

function isWateringType(t: ActivityType): boolean {
  return t === "irrigation" || t === "fertilizing";
}

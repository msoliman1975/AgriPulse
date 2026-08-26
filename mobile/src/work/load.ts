/**
 * Everything a scout owes, across every farm they are granted.
 *
 * The app used to hold one farm at a time. A scout on two farms picked one in
 * a settings screen and the whole app — tasks, records, capture — silently
 * meant *that* farm until they went back and changed it. Work on the other
 * farm was not late, not empty and not shown: it did not exist. That is the
 * wrong shape for a person who walks two farms in one day.
 *
 * So the farm stops being a mode and becomes a column. Every list loads every
 * granted farm and each row carries the farm it came from, which is what lets
 * the Tasks screen group by farm first and the counts add up to the truth.
 *
 * **Per-farm failure is not total failure.** Farms are fetched independently
 * and a farm that throws is named in `failed` rather than taking the other
 * farms' work down with it. A scout stands in a field on one bar of signal,
 * so one farm timing out while four answer is the normal case, and four
 * farms' work is still a usable day.
 *
 * This used to also cover a farm that could *never* load: a scout in two
 * tenants carries one `tenant_id` in their token, so the other tenant's farm
 * was unreadable for ever and sat in `failed` looking like a network problem.
 * A person now belongs to one tenant — refused at both enrolment doors and
 * enforced by a unique index — and `/me` returns only the scopes of their
 * active membership. So everything in `failed` is a retry away from working,
 * which is what the warning on the Tasks screen now means.
 */

import {
  listBlocks,
  listMyWork,
  listVisits,
  type Block,
  type Visit,
  type WorkItem,
} from "@/api/client";
import type { FarmScope } from "@/api/me";

export interface WorkSet {
  /** Assigned to this scout and still open. */
  mine: WorkItem[];
  /** Unclaimed and takeable. */
  available: WorkItem[];
  /** Closed by this scout. */
  done: WorkItem[];
  /** Blocks per farm, for the capture pickers and for naming a row. */
  blocksByFarm: Record<string, Block[]>;
  /** Ids of farms whose fetch threw. Empty is the normal case. */
  failed: string[];
}

export const EMPTY_WORK: WorkSet = {
  mine: [],
  available: [],
  done: [],
  blocksByFarm: {},
  failed: [],
};

/** A visit rendered as a work item, so one detail screen serves both kinds. */
function asWorkItem(v: Visit, blockName: string | null, farmName: string): WorkItem {
  return {
    kind: "scouting_visit",
    id: v.id,
    farm_id: v.farm_id,
    farm_name: farmName,
    block_id: v.block_id,
    block_name: blockName,
    title: v.title,
    detail: v.instruction,
    status: v.status,
    category: v.origin,
    severity: v.severity,
    priority: v.priority,
    due_at: v.due_by,
    completed_at: v.completed_at ?? null,
    template_id: v.template_id,
    source: v.source,
  };
}

interface FarmWork {
  mine: WorkItem[];
  available: WorkItem[];
  done: WorkItem[];
  blocks: Block[];
}

async function loadFarm(farmId: string, farmName: string): Promise<FarmWork> {
  const [work, mineVisits, claimable, closed, blocks] = await Promise.all([
    listMyWork(farmId),
    listVisits(farmId, { mine: true }),
    listVisits(farmId, { claimable: true }),
    listVisits(farmId, { mine: true, status: ["completed"] }),
    // A missing block list costs a row its place name, which is survivable.
    // A missing work list is the screen's whole reason to exist, which is not
    // — so only this one is allowed to fail quietly.
    listBlocks(farmId).catch(() => [] as Block[]),
  ]);

  const blockName = (id: string | null): string | null => {
    const found = blocks.find((b) => b.id === id);
    return found ? found.name || found.code : null;
  };

  // `/me/work` merges visits and board work but does not carry the group
  // counters, and the visit list carries them but not board work. Joining by
  // id keeps both rather than choosing which half to lose.
  const sourceById = new Map(mineVisits.map((v) => [v.id, v.source]));

  return {
    mine: work.map((w) => ({
      ...w,
      farm_name: farmName,
      block_name: blockName(w.block_id),
      source: sourceById.get(w.id) ?? null,
    })),
    available: claimable.map((v) => asWorkItem(v, blockName(v.block_id), farmName)),
    done: closed.map((v) => asWorkItem(v, blockName(v.block_id), farmName)),
    blocks,
  };
}

/**
 * Load every granted farm at once.
 *
 * Five requests per farm, run in parallel across farms as well as within one.
 * In production a scout holds one or two farms; the ceiling that would make
 * this a problem — a supervisor granted a dozen — is not a shape the app has,
 * and paging it would trade a real bug now for a hypothetical one later.
 */
export async function loadWork(
  farms: FarmScope[],
  farmName: (farmId: string) => string,
): Promise<WorkSet> {
  const results = await Promise.all(
    farms.map((f) =>
      loadFarm(f.farm_id, farmName(f.farm_id))
        .then((w) => ({ farmId: f.farm_id, work: w }))
        .catch(() => ({ farmId: f.farm_id, work: null })),
    ),
  );

  const out: WorkSet = { mine: [], available: [], done: [], blocksByFarm: {}, failed: [] };
  for (const { farmId, work } of results) {
    if (work === null) {
      out.failed.push(farmId);
      continue;
    }
    out.mine.push(...work.mine);
    out.available.push(...work.available);
    out.done.push(...work.done);
    out.blocksByFarm[farmId] = work.blocks;
  }
  return out;
}

import { describe, expect, it } from "vitest";

import type { SavedPlan } from "@/api/agriOperation";
import {
  addDays,
  daysBetween,
  draftFromSaved,
  draftProblems,
  emptyDraft,
  setOverride,
  toggleCode,
  toRequest,
} from "./planDraft";

describe("planDraft", () => {
  const base = emptyDraft("tpl", new Date("2026-11-05T12:00:00Z"));

  it("starts with a season for this year and today's date", () => {
    expect(base.seasonLabel).toBe("Main season 2026");
    expect(base.sameDate).toBe("2026-11-05");
    expect(draftProblems(base)).toEqual(["plan.err.noBlocks"]);
  });

  it("needs a date for every block in per-block mode", () => {
    const d = {
      ...base,
      blockIds: ["b1", "b2"],
      startMode: "per_block" as const,
      perBlockDates: { b1: "2026-11-01" },
    };
    expect(draftProblems(d)).toEqual(["plan.err.noDate"]);
    const req = toRequest({ ...d, perBlockDates: { b1: "2026-11-01", b2: "2026-11-09" } });
    expect(req.blocks).toEqual([
      { block_id: "b1", start_date: "2026-11-01" },
      { block_id: "b2", start_date: "2026-11-09" },
    ]);
  });

  it("toggles exclusions and keeps overrides only for blocks in the plan", () => {
    let d = { ...base, blockIds: ["b1"] };
    d = toggleCode(d, "spraying-1");
    expect(d.excludedCodes).toEqual(["spraying-1"]);
    d = toggleCode(d, "spraying-1");
    expect(d.excludedCodes).toEqual([]);
    d = setOverride(d, "b1", "pruning-1", "2026-12-01");
    d = setOverride(d, "b9", "pruning-1", "2026-12-01");
    expect(toRequest(d).date_overrides).toEqual({ b1: { "pruning-1": "2026-12-01" } });
    d = setOverride(d, "b1", "pruning-1", null);
    expect(toRequest(d).date_overrides).toEqual({});
  });

  it("round-trips a saved plan", () => {
    const saved = {
      id: "p1",
      template_id: "tpl",
      season_label: "Main season 2026",
      season_year: 2026,
      start_mode: "same",
      blocks: [
        { block_id: "b1", start_date: "2026-11-05" },
        { block_id: "b2", start_date: "2026-11-05" },
      ],
      excluded_codes: ["thinning-1"],
      activity_edits: { "fertilizing-1": { product_name: "Farm urea" } },
      custom_activities: [],
      date_overrides: { b1: { "pruning-1": "2026-12-01" } },
    } as unknown as SavedPlan;
    const d = draftFromSaved(saved);
    expect(d.id).toBe("p1");
    expect(toRequest(d)).toEqual({
      template_id: "tpl",
      season_label: "Main season 2026",
      season_year: 2026,
      start_mode: "same",
      blocks: saved.blocks,
      excluded_codes: ["thinning-1"],
      activity_edits: { "fertilizing-1": { product_name: "Farm urea" } },
      custom_activities: [],
      date_overrides: { b1: { "pruning-1": "2026-12-01" } },
    });
  });

  it("date helpers", () => {
    expect(addDays("2026-12-30", 3)).toBe("2027-01-02");
    expect(daysBetween("2026-12-30", "2027-01-02")).toBe(3);
  });
});

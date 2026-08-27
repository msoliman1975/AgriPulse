import { describe, expect, it } from "vitest";

import type { ActionItem } from "@/api/actionCenter";
import { defaultAssignee } from "@/modules/actionCenter/lib/assignee";

const item = (over: Partial<ActionItem> = {}): ActionItem => ({
  id: "i1",
  kind: "recommendation",
  status: "needs_action",
  native_status: "open",
  farm_id: "f1",
  block_id: "b1",
  block_code: "B-01",
  block_name_ar: null,
  block_name: null,
  cell: null,
  action_type: "scout",
  severity: "warning",
  title_en: "t",
  title_ar: null,
  detail_en: null,
  detail_ar: null,
  tree_code: null,
  tree_version: null,
  confidence: null,
  created_at: "2026-08-09T00:00:00Z",
  valid_until: null,
  due_bucket: "none",
  due_date: null,
  responsible_membership_id: null,
  assigned_membership_id: null,
  activity_id: null,
  scheduled_date: null,
  acknowledged_at: null,
  resolved_at: null,
  applied_at: null,
  dismissed_at: null,
  deferred_until: null,
  snoozed_until: null,
  why: null,
  reasoning: {},
  tree_path: [],
  actions: {},
  aggregation: {
    is_group: false,
    member_count: 0,
    member_kind: "cell",
    previous_member_count: 0,
    trend: "unknown",
  },
  recurrence: {
    state: "new",
    occurrence_count: 1,
    day_streak: 1,
    first_seen_at: null,
    last_seen_at: null,
  },
  ...over,
});

describe("defaultAssignee", () => {
  it("defaults to the block's responsible member for a single item", () => {
    // The shipped bug: this returned "" for every undispatched item, so the
    // dialog always showed the placeholder and never a name.
    expect(defaultAssignee([item({ responsible_membership_id: "m-ahmed" })])).toBe("m-ahmed");
  });

  it("does NOT read assigned_membership_id", () => {
    // That field is only set after dispatch. Reading it is what broke the
    // default for the one case that matters — an item you have not sent yet.
    const i = item({ responsible_membership_id: null, assigned_membership_id: "m-someone" });
    expect(defaultAssignee([i])).toBe("");
  });

  it("keeps the owner when every item in the batch shares one block", () => {
    const batch = [
      item({ id: "a", responsible_membership_id: "m-mona" }),
      item({ id: "b", responsible_membership_id: "m-mona" }),
    ];
    expect(defaultAssignee(batch)).toBe("m-mona");
  });

  it("falls back to per-item resolution when blocks disagree", () => {
    // Picking one name for a mixed batch would silently reassign other
    // people's blocks; "" tells the server to resolve each item separately.
    const batch = [
      item({ id: "a", block_id: "b1", responsible_membership_id: "m-mona" }),
      item({ id: "b", block_id: "b2", responsible_membership_id: "m-karim" }),
    ];
    expect(defaultAssignee(batch)).toBe("");
  });

  it("falls back when one block in the batch names nobody", () => {
    const batch = [
      item({ id: "a", responsible_membership_id: "m-mona" }),
      item({ id: "b", responsible_membership_id: null }),
    ];
    expect(defaultAssignee(batch)).toBe("");
  });

  it("is empty when nobody is responsible at all", () => {
    expect(defaultAssignee([item({ responsible_membership_id: null })])).toBe("");
  });

  it("is empty for an empty batch rather than throwing", () => {
    expect(defaultAssignee([])).toBe("");
  });
});

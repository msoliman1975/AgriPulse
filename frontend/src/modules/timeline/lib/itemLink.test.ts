import { describe, expect, it } from "vitest";

import type { TimelineEvent, TimelineEventKind } from "@/api/timeline";
import { itemLinkFor } from "./itemLink";

function ev(kind: TimelineEventKind, blockId: string | null = "b1"): TimelineEvent {
  return {
    kind,
    id: "x",
    at: "2026-06-03T09:00:00Z",
    day: "2026-06-03",
    block_id: blockId,
    block_name: null,
    block_name_ar: null,
    block_code: null,
    code: null,
    title_en: "",
    title_ar: null,
    detail: null,
    severity: null,
    point: null,
  };
}

describe("itemLinkFor", () => {
  it("sends an alert and a recommendation to the unified queue", () => {
    // Not /alerts or /recommendations. Those stay routed until the Action
    // Center is signed off, but the queue is where the row can be acted on.
    expect(itemLinkFor(ev("alert"), "f1")).toBe("/action-center/f1");
    expect(itemLinkFor(ev("recommendation"), "f1")).toBe("/action-center/f1");
  });

  it("sends a visit and a flag to the board", () => {
    expect(itemLinkFor(ev("visit"), "f1")).toBe("/board/f1");
    expect(itemLinkFor(ev("flag"), "f1")).toBe("/board/f1");
  });

  it("sends a signal to the signals log", () => {
    expect(itemLinkFor(ev("signal"), "f1")).toBe("/signals/f1");
  });

  it("sends a block-scoped datapoint to its block", () => {
    expect(itemLinkFor(ev("stage"), "f1")).toBe("/farms/f1/blocks/b1");
    expect(itemLinkFor(ev("activity"), "f1")).toBe("/farms/f1/blocks/b1");
  });

  it("offers no link when there is nothing narrower than the farm", () => {
    // No link is better than one that lands the reader on a screen with
    // nothing to do with what they clicked.
    expect(itemLinkFor(ev("activity", null), "f1")).toBeNull();
  });
});

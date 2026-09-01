import { describe, expect, it } from "vitest";

import type { TimelineEvent } from "@/api/timeline";
import { cardKey, selectCards, type SlotState } from "./cards";
import type { FadedEvent } from "./frames";
import type { BlockAnchors } from "./marks";

const ANCHORS: BlockAnchors = new Map([["b1", [31.6, 30.6]]]);

function ev(over: Partial<TimelineEvent> & { id: string }): TimelineEvent {
  return {
    kind: "alert",
    at: "2026-06-03T09:00:00Z",
    day: "2026-06-03",
    block_id: "b1",
    block_name: "North ridge",
    block_name_ar: null,
    block_code: "B-01",
    code: "inspect",
    title_en: `Alert ${over.id}`,
    title_ar: null,
    detail: null,
    severity: "critical",
    point: null,
    ...over,
  };
}

function faded(events: readonly TimelineEvent[], opacity = 1): FadedEvent[] {
  return events.map((event) => ({ event, opacity }));
}

const SLOTS = 6;
const HOLD = 900;

describe("selectCards", () => {
  it("numbers the slots from one and fills them best-ranked first", () => {
    const critical = ev({ id: "c", severity: "critical" });
    const watch = ev({ id: "w", severity: "warning" });
    const info = ev({ id: "i", severity: "info" });

    const { cards } = selectCards(faded([info, watch, critical]), ANCHORS, [], 0, SLOTS, HOLD);

    expect(cards.map((c) => c.number)).toEqual([1, 2, 3]);
    expect(cards.map((c) => c.event.id)).toEqual(["c", "w", "i"]);
  });

  it("keeps a card's number when its rank falls", () => {
    // The number is the ONLY tie between a card and its mark on the map. A
    // number that moves under the reader is worse than no number, so a
    // seated card keeps its slot even once fresher datapoints outrank it.
    const older = ev({ id: "old", severity: "info" });
    const first = selectCards(faded([older]), ANCHORS, [], 0, SLOTS, HOLD);
    expect(first.cards[0].number).toBe(1);

    const fresher = ev({ id: "new", severity: "critical" });
    const second = selectCards(
      [...faded([fresher]), ...faded([older], 0.5)],
      ANCHORS,
      first.slots,
      2000,
      SLOTS,
      HOLD,
    );

    const byId = new Map(second.cards.map((c) => [c.event.id, c.number]));
    expect(byId.get("old")).toBe(1);
    expect(byId.get("new")).toBe(2);
  });

  it("drops the slot the moment its datapoint leaves the map, hold or not", () => {
    const gone = ev({ id: "gone" });
    const first = selectCards(faded([gone]), ANCHORS, [], 0, SLOTS, HOLD);
    expect(first.cards).toHaveLength(1);

    // Well inside the hold window, and the datapoint has faded out. The
    // dock may never show something the map has stopped drawing.
    const second = selectCards([], ANCHORS, first.slots, 100, SLOTS, HOLD);
    expect(second.cards).toHaveLength(0);
    expect(second.slots).toHaveLength(0);
  });

  it("holds a slot against a better-ranked challenger, then gives way", () => {
    const seated = ev({ id: "seated", severity: "info" });
    const first = selectCards(faded([seated]), ANCHORS, [], 0, 1, HOLD);
    expect(first.cards.map((c) => c.event.id)).toEqual(["seated"]);

    const better = ev({ id: "better", severity: "critical" });
    // 400 ms later — inside the hold. On a busy day the ranking turns over
    // every frame, and without this the one-slot dock would restack at
    // playback speed and be unreadable.
    const held = selectCards(faded([seated, better]), ANCHORS, first.slots, 400, 1, HOLD);
    expect(held.cards.map((c) => c.event.id)).toEqual(["seated"]);

    // 1000 ms later — past it.
    const swapped = selectCards(faded([seated, better]), ANCHORS, held.slots, 1000, 1, HOLD);
    expect(swapped.cards.map((c) => c.event.id)).toEqual(["better"]);
    expect(swapped.cards[0].number).toBe(1);
  });

  it("gives no slot to a datapoint with nowhere to stand", () => {
    // Neither its own point nor a block we hold a boundary for. A card
    // that points at empty ground is worse than no card.
    const nowhere = ev({ id: "n", block_id: null });
    const { cards, overflow } = selectCards(faded([nowhere]), ANCHORS, [], 0, SLOTS, HOLD);
    expect(cards).toHaveLength(0);
    expect(overflow).toBe(1);
  });

  it("counts the overflow over everything the rail shows", () => {
    const events = Array.from({ length: 10 }, (_, n) => ev({ id: `e${n}` }));
    const { cards, overflow } = selectCards(faded(events), ANCHORS, [], 0, SLOTS, HOLD);
    // "+4 more" has to agree with the list the reader opens next.
    expect(cards).toHaveLength(6);
    expect(overflow).toBe(4);
  });

  it("prefers a datapoint's own point over its block's anchor", () => {
    const located = ev({
      id: "p",
      point: { type: "Point", coordinates: [31.7, 30.7] },
    });
    const { cards } = selectCards(faded([located]), ANCHORS, [], 0, SLOTS, HOLD);
    expect(cards[0].coordinates).toEqual([31.7, 30.7]);
  });

  it("flags a block-scoped datapoint so it draws a ring, not a pin", () => {
    const activity = ev({ id: "a", kind: "activity", severity: null });
    const alert = ev({ id: "b" });
    const { cards } = selectCards(faded([activity, alert]), ANCHORS, [], 0, SLOTS, HOLD);
    const byId = new Map(cards.map((c) => [c.event.id, c.blockScoped]));
    expect(byId.get("a")).toBe(true);
    expect(byId.get("b")).toBe(false);
  });

  it("never seats one datapoint in two slots", () => {
    const one = ev({ id: "one" });
    // A malformed carry-in, which is what a bug elsewhere would look like.
    const bogus: SlotState[] = [
      { key: cardKey(one), number: 1, since: 0 },
      { key: cardKey(one), number: 2, since: 0 },
    ];
    const { cards } = selectCards(faded([one]), ANCHORS, bogus, 5000, SLOTS, HOLD);
    expect(cards).toHaveLength(1);
    expect(cards[0].number).toBe(1);
  });
});

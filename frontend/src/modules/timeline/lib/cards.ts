// Which of the day's datapoints get a card beside the map, and which slot
// each one holds.
//
// The problem this solves is not "which are the most important" — the mark
// layer already ranks them with `eventSortKey`. It is that the ranking
// turns over between frames. On 5 August this farm records 108 alerts; a
// dock that simply showed the current top six would restack on every tick
// and be unreadable at any playback speed.
//
// So the dock is SIX FIXED SLOTS, not a sorted list:
//
//   - A card keeps its slot, and therefore its number, for as long as it is
//     on the dock. The number is the whole tie between a card and its mark,
//     so a number that moves is worse than no number.
//   - A slot is held against displacement for `CARD_MIN_SLOT_MS`. After
//     that a better-ranked datapoint may take it.
//   - A card whose datapoint has faded off the map leaves AT ONCE, held or
//     not. The dock may never show something the map does not.
//
// Pure, and time is an argument, so the whole thing is unit-testable
// without a clock or a map.

import type { TimelineEvent } from "@/api/timeline";
import { anchorFor, eventSortKey, type BlockAnchors } from "./marks";
import type { FadedEvent } from "./frames";

/** A datapoint holding one slot on the dock. */
export interface CardedEvent {
  /** `kind:id`. Ids are only unique within a source table. */
  key: string;
  event: TimelineEvent;
  /** 0..1 from the fade curve, the same value the mark draws with. */
  opacity: number;
  /** 1-based slot. Printed on the card AND on the map badge. */
  number: number;
  /** Where the badge stands. Never null — unplaceable events get no card. */
  coordinates: [number, number];
  /**
   * True when the datapoint is a property of the block rather than of a
   * spot in it — a stage change, a completed activity, a recommendation.
   * The badge is drawn differently for these, because putting a pin on one
   * would invent a precision nobody recorded.
   */
  blockScoped: boolean;
}

/** What `selectCards` needs to remember between frames. */
export interface SlotState {
  key: string;
  number: number;
  /** `performance.now()`-style timestamp of when this card took its slot. */
  since: number;
}

export interface CardSelection {
  cards: CardedEvent[];
  /** Visible datapoints with no card. Drives the "+N more" row. */
  overflow: number;
  /** Carry into the next call. */
  slots: SlotState[];
}

/** The kinds that stand for a whole block rather than for a point in it. */
const BLOCK_SCOPED = new Set(["stage", "activity", "recommendation"]);

export function cardKey(event: TimelineEvent): string {
  return `${event.kind}:${event.id}`;
}

/**
 * Fill the dock for one frame.
 *
 * `previous` is the slot table from the last call; pass `[]` on the first.
 * `now` is any monotonic millisecond clock.
 */
export function selectCards(
  faded: readonly FadedEvent[],
  anchors: BlockAnchors,
  previous: readonly SlotState[],
  now: number,
  slotCount: number,
  minSlotMs: number,
): CardSelection {
  // Only datapoints we can stand somewhere. One with neither a point nor a
  // block cannot be pointed at, and a card that points nowhere is worse
  // than no card.
  const placeable: { candidate: CardedEvent; rank: number }[] = [];
  for (const { event, opacity } of faded) {
    const coordinates = anchorFor(event, anchors);
    if (coordinates === null) continue;
    placeable.push({
      candidate: {
        key: cardKey(event),
        event,
        opacity,
        // Overwritten once the slot is known. Never read before then.
        number: 0,
        coordinates,
        blockScoped: BLOCK_SCOPED.has(event.kind),
      },
      rank: eventSortKey(event, opacity),
    });
  }
  placeable.sort((a, b) => a.rank - b.rank || a.candidate.key.localeCompare(b.candidate.key));

  const byKey = new Map(placeable.map((p) => [p.candidate.key, p]));

  // Pass 1 — every card still on the map keeps its own slot and its own
  // number. A datapoint that has faded out is simply absent here, which is
  // how it leaves the dock the moment it leaves the map.
  const taken = new Map<number, SlotState>();
  const seated = new Set<string>();
  for (const slot of previous) {
    if (!byKey.has(slot.key)) continue;
    if (slot.number < 1 || slot.number > slotCount) continue;
    if (taken.has(slot.number) || seated.has(slot.key)) continue;
    taken.set(slot.number, slot);
    seated.add(slot.key);
  }

  // Pass 2 — fill the free slots, best-ranked first. Ranking only decides
  // WHO gets in; the slot they land in is the lowest free number, so the
  // dock fills top-down and a card never moves once seated.
  for (const { candidate } of placeable) {
    if (seated.has(candidate.key)) continue;
    let n: number | null = null;
    for (let i = 1; i <= slotCount; i += 1) {
      if (!taken.has(i)) {
        n = i;
        break;
      }
    }
    if (n === null) break;
    taken.set(n, { key: candidate.key, number: n, since: now });
    seated.add(candidate.key);
  }

  // Pass 3 — displacement. A slot past its hold whose occupant ranks worse
  // than someone waiting gives way. Worst occupant first, best challenger
  // first, so the swaps that happen are the ones worth the disruption.
  const waiting = placeable.filter((p) => !seated.has(p.candidate.key));
  if (waiting.length > 0) {
    const occupants = [...taken.values()]
      .map((slot) => ({ slot, rank: byKey.get(slot.key)?.rank ?? Infinity }))
      .sort((a, b) => b.rank - a.rank);
    let w = 0;
    for (const occ of occupants) {
      if (w >= waiting.length) break;
      if (now - occ.slot.since < minSlotMs) continue; // still held
      const challenger = waiting[w];
      if (challenger.rank >= occ.rank) break; // nobody left who is better
      taken.set(occ.slot.number, {
        key: challenger.candidate.key,
        number: occ.slot.number,
        since: now,
      });
      w += 1;
    }
  }

  const slots = [...taken.values()].sort((a, b) => a.number - b.number);
  const cards: CardedEvent[] = [];
  for (const slot of slots) {
    const hit = byKey.get(slot.key);
    if (!hit) continue;
    cards.push({ ...hit.candidate, number: slot.number });
  }

  return {
    cards,
    // Counted over everything the rail shows, not only the placeable ones:
    // "+103 more" has to agree with the list the reader opens next.
    overflow: Math.max(faded.length - cards.length, 0),
    slots,
  };
}

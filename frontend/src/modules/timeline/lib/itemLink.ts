// Where "open this" goes, per datapoint kind.
//
// There is no per-item page for ANY of the seven kinds — checked against
// `App.tsx`. Every destination below is a list screen, so the link lands
// the reader on the right queue rather than on the row itself. When those
// screens grow a focus parameter this is the one file that changes.
//
// No capability check here. The timeline endpoint already drops the kinds
// the caller cannot read and names them in `omitted_kinds`, so a datapoint
// that reached this screen is one its reader is allowed to open.

import type { TimelineEvent } from "@/api/timeline";

export function itemLinkFor(event: TimelineEvent, farmId: string): string | null {
  switch (event.kind) {
    case "alert":
    case "recommendation":
      // The unified queue, not `/alerts` or `/recommendations`. Those two
      // stay routed until the Action Center is signed off, but the queue is
      // where the row can actually be acted on.
      return `/action-center/${farmId}`;
    case "signal":
      return `/signals/${farmId}`;
    case "visit":
    case "flag":
      return `/board/${farmId}`;
    case "stage":
    case "activity":
      // Block-scoped, so the block page is the honest landing. Without a
      // block there is nothing narrower than the farm and no link is
      // better than one that goes nowhere useful.
      return event.block_id ? `/farms/${farmId}/blocks/${event.block_id}` : null;
    default:
      return null;
  }
}

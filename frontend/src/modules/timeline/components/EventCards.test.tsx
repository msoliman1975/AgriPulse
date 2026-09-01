// The dock, on its own.
//
// The page test proves the dock and the rail agree about what is on the
// day. What is left to prove here is the part only the dock does: the
// connector measurement, the link out, and the overflow row.

import { fireEvent, render, screen, within } from "@testing-library/react";
import { createRef } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { TimelineEvent } from "@/api/timeline";
import { setupTestI18n } from "@/i18n/testing";
import type { CardedEvent } from "../lib/cards";
import { EventCards } from "./EventCards";

function card(over: Partial<TimelineEvent> & { id: string }, number: number): CardedEvent {
  const event: TimelineEvent = {
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
  return {
    key: `${event.kind}:${event.id}`,
    event,
    opacity: 1,
    number,
    coordinates: [31.6, 30.6],
    blockScoped: false,
  };
}

function renderDock(
  cards: CardedEvent[],
  overflow = 0,
  handlers: Partial<{
    onActivate: (id: string | null, from: { x: number; y: number } | null) => void;
    onSelect: (id: string) => void;
    onShowAll: () => void;
  }> = {},
) {
  const containerRef = createRef<HTMLDivElement>();
  render(
    <MemoryRouter>
      <div ref={containerRef}>
        <EventCards
          farmId="f1"
          cards={cards}
          overflow={overflow}
          activeEventId={null}
          onActivate={handlers.onActivate ?? vi.fn()}
          onSelect={handlers.onSelect ?? vi.fn()}
          containerRef={containerRef}
          onShowAll={handlers.onShowAll ?? vi.fn()}
        />
      </div>
    </MemoryRouter>,
  );
  return within(screen.getByRole("list", { name: "Highlighted datapoints" }));
}

describe("EventCards", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
  });

  it("prints the number, the kind, the block and the title", () => {
    const dock = renderDock([card({ id: "a1", title_en: "NDVI fell 22% in seven days" }, 1)]);
    expect(dock.getByText("1")).toBeInTheDocument();
    expect(dock.getByText("Alert")).toBeInTheDocument();
    expect(dock.getByText("North ridge")).toBeInTheDocument();
    expect(dock.getByText("NDVI fell 22% in seven days")).toBeInTheDocument();
  });

  it("links out to the screen that can act on the datapoint", () => {
    const dock = renderDock([card({ id: "a1" }, 1)]);
    expect(dock.getByRole("link", { name: "Open" })).toHaveAttribute("href", "/action-center/f1");
  });

  it("reports where the connector should start when the reader points at one", () => {
    // Measured once, on hover. The card does not move while the map pans,
    // so there is nothing here to recompute per frame — only the map end
    // of the line is re-projected.
    const onActivate = vi.fn();
    const dock = renderDock([card({ id: "a1" }, 1)], 0, { onActivate });

    fireEvent.mouseEnter(dock.getByRole("listitem"));
    expect(onActivate).toHaveBeenCalledTimes(1);
    const [eventId, from] = onActivate.mock.calls[0];
    expect(eventId).toBe("a1");
    // jsdom reports every rect as zero, so the value cannot be asserted.
    // That an ANCHOR was produced at all can be, and null here is the
    // failure: it means the line had no start and was never drawn.
    expect(from).not.toBeNull();

    fireEvent.mouseLeave(dock.getByRole("listitem"));
    expect(onActivate).toHaveBeenLastCalledWith(null, null);
  });

  it("says how many datapoints it left out", () => {
    const onShowAll = vi.fn();
    const dock = renderDock([card({ id: "a1" }, 1)], 103, { onShowAll });
    const more = dock.getByRole("button", { name: "+103 more on the list" });
    fireEvent.click(more);
    // It jumps the rail, rather than opening a second list. The rail is
    // the full list; the dock is a shortlist on top of it.
    expect(onShowAll).toHaveBeenCalledTimes(1);
  });

  it("draws nothing at all when the day is empty", () => {
    render(
      <MemoryRouter>
        <EventCards
          farmId="f1"
          cards={[]}
          overflow={0}
          activeEventId={null}
          onActivate={vi.fn()}
          onSelect={vi.fn()}
          containerRef={createRef<HTMLDivElement>()}
          onShowAll={vi.fn()}
        />
      </MemoryRouter>,
    );
    expect(screen.queryByRole("list", { name: "Highlighted datapoints" })).toBeNull();
  });
});

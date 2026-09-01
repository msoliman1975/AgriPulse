// @vitest-environment jsdom
import { describe, expect, it } from "vitest";

import { buildMarkElement, updateMarkElement, type CardMark } from "./cardMarkElement";

function mark(over: Partial<CardMark> = {}): CardMark {
  return {
    eventId: "a1",
    number: 3,
    coordinates: [31.6, 30.6],
    opacity: 1,
    color: "#A32D2D",
    iconUrl: "data:image/png;base64,AAA",
    blockScoped: false,
    label: "3. NDVI fell 22% in seven days",
    ...over,
  };
}

describe("buildMarkElement", () => {
  it("prints the slot number on the badge", () => {
    // The number IS the tie between the card and the spot. The symbol
    // layer cannot carry one — a layer with a `text-field` draws nothing
    // at all until the style's glyph endpoint answers — which is the whole
    // reason these six are DOM nodes.
    const el = buildMarkElement(mark());
    expect(el.querySelector(".tl-mark-badge")?.textContent).toBe("3");
  });

  it("colours the badge and names the datapoint", () => {
    const el = buildMarkElement(mark());
    const badge = el.querySelector<HTMLElement>(".tl-mark-badge");
    expect(badge?.style.backgroundColor).toBe("rgb(163, 45, 45)");
    expect(el.getAttribute("aria-label")).toBe("3. NDVI fell 22% in seven days");
    expect(el.title).toBe("3. NDVI fell 22% in seven days");
  });

  it("draws the kind's glyph when the datapoint has one", () => {
    const el = buildMarkElement(mark());
    const img = el.querySelector<HTMLImageElement>(".tl-mark-glyph");
    expect(img?.getAttribute("src")).toBe("data:image/png;base64,AAA");
  });

  it("draws a ring and no pin for a block-scoped datapoint", () => {
    // A completed activity belongs to the block, not to a spot in it.
    // Putting a pin on one would invent a precision nobody recorded.
    const el = buildMarkElement(mark({ blockScoped: true, iconUrl: null }));
    expect(el.querySelector(".tl-mark-glyph")).toBeNull();
    expect(el.classList.contains("tl-mark--block")).toBe(true);
  });

  it("carries the fade opacity", () => {
    const el = buildMarkElement(mark({ opacity: 0.4375 }));
    expect(el.style.opacity).toBe("0.4375");
  });
});

describe("updateMarkElement", () => {
  it("writes the new values onto the same node", () => {
    // Mutated in place, never rebuilt: a marker that is removed and
    // re-added restarts its enter animation, which at playback speed reads
    // as a flicker on every frame.
    const el = buildMarkElement(mark());
    updateMarkElement(el, mark({ number: 5, opacity: 0.7, color: "#854F0B", label: "5. Copper" }));

    expect(el.querySelector(".tl-mark-badge")?.textContent).toBe("5");
    expect(el.style.opacity).toBe("0.7");
    expect(el.getAttribute("aria-label")).toBe("5. Copper");
  });
});

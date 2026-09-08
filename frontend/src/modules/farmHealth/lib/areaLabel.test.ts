import type { TFunction } from "i18next";
import { describe, expect, it } from "vitest";

import { areaLabel } from "./areaLabel";

/** Returns the key and its options, so the call itself can be asserted. */
const t = ((key: string, options?: Record<string, unknown>) =>
  options ? `${key}(${JSON.stringify(options)})` : key) as unknown as TFunction;

describe("areaLabel", () => {
  it("asks for a translation rather than building English", () => {
    // The whole point: the library returns parts, and the words come from
    // the locale file. A name assembled as English in the library would
    // reach the Arabic screen in English.
    expect(areaLabel(t, { kind: "whole" }, 1)).toBe("farmHealth:area.whole");
    expect(areaLabel(t, { kind: "centre" }, 1)).toBe("farmHealth:area.centre");
  });

  it("counts the spots of a scattered area", () => {
    expect(areaLabel(t, { kind: "scattered" }, 3)).toBe(
      'farmHealth:area.scattered({"count":3})',
    );
  });

  it("puts the direction inside the sentence for a large area", () => {
    expect(areaLabel(t, { kind: "most", direction: "south-east" }, 1)).toBe(
      'farmHealth:area.most({"direction":"farmHealth:direction.south-east"})',
    );
  });

  it("falls back to a plain name when a large area has no direction", () => {
    expect(areaLabel(t, { kind: "most" }, 1)).toBe("farmHealth:area.mostPlain");
  });

  it("uses the titled form when the direction is the whole name", () => {
    expect(areaLabel(t, { kind: "direction", direction: "north-west" }, 1)).toBe(
      "farmHealth:directionTitle.north-west",
    );
  });
});

import { describe, expect, it } from "vitest";

import { safeReturnTo } from "./returnTo";

describe("safeReturnTo", () => {
  it("keeps an in-app path with its query", () => {
    expect(safeReturnTo("/decision-trees-beta/x?tab=readiness")).toBe(
      "/decision-trees-beta/x?tab=readiness",
    );
  });

  it.each([null, "", "https://evil.example", "//evil.example", "/\\evil.example", "javascript:x"])(
    "drops %s",
    (v) => {
      expect(safeReturnTo(v)).toBeNull();
    },
  );
});

// The family tabs are generated from INDEX_FAMILIES, so an index missing from
// that table does not error — it just stops being reachable anywhere in the
// dock. These keep the three index tables in lock-step instead.
import { describe, expect, it } from "vitest";

import {
  BLOCK_LEVEL_INDICES,
  FAMILY_PRIMARY,
  INDEX_FAMILIES,
  INDEX_META,
  isBlockLevel,
  MAP_INDEX_ORDER,
} from "./constants";

describe("index families", () => {
  it("files every index the map can colour by into exactly one family", () => {
    const filed = INDEX_FAMILIES.flatMap((f) => f.indices);
    expect([...filed].sort()).toEqual([...MAP_INDEX_ORDER].sort());
    expect(new Set(filed).size).toBe(filed.length);
  });

  it("agrees with the family recorded on each index", () => {
    for (const family of INDEX_FAMILIES) {
      for (const code of family.indices) {
        expect(INDEX_META[code].family).toBe(family.key);
      }
    }
  });

  it("gives each family exactly one block-level index to chart", () => {
    for (const family of INDEX_FAMILIES) {
      const blockLevel = family.indices.filter(isBlockLevel);
      // More than one and the tab would have to choose; none and it would have
      // nothing to plot at all.
      expect(blockLevel).toHaveLength(1);
      expect(FAMILY_PRIMARY[family.key]).toBe(blockLevel[0]);
    }
    expect(Object.values(FAMILY_PRIMARY).sort()).toEqual([...BLOCK_LEVEL_INDICES].sort());
  });
});

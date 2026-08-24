import { beforeEach, describe, expect, it, vi } from "vitest";

import { layoutTree, LAYOUT_CONSTANTS, type CompiledTree } from "./treeLayout";
import {
  DEFAULT_CANVAS_HEIGHT,
  MAX_CANVAS_HEIGHT,
  MIN_CANVAS_HEIGHT,
  applyManualPositions,
  clampCanvasHeight,
  loadCanvasPrefs,
  normalizePrefs,
  prunePositions,
  saveCanvasPrefs,
} from "./manualPositions";

const { NODE_WIDTH, NODE_HEIGHT } = LAYOUT_CONSTANTS;

const COMPILED: CompiledTree = {
  root: "root",
  nodes: {
    root: { label_en: "root check", on_match: "hit", on_miss: "skip" },
    hit: { outcome: { action_type: "irrigate", text_en: "water it" } },
    skip: { outcome: { action_type: "no_action" } },
  },
};

function baseLayout() {
  return layoutTree(COMPILED);
}

describe("applyManualPositions", () => {
  it("returns the auto-layout untouched when nothing has been moved", () => {
    const auto = baseLayout();
    expect(applyManualPositions(auto, {})).toBe(auto);
  });

  it("ignores positions for nodes that are no longer in the tree", () => {
    const auto = baseLayout();
    expect(applyManualPositions(auto, { deletedNode: { x: 10, y: 10 } })).toBe(auto);
  });

  it("moves only the node that was dragged", () => {
    const auto = baseLayout();
    const autoSkip = auto.nodes.find((n) => n.id === "skip")!;
    const moved = applyManualPositions(auto, { hit: { x: 900, y: 700 } });

    const hit = moved.nodes.find((n) => n.id === "hit")!;
    expect(hit.x).toBe(900);
    expect(hit.y).toBe(700);

    const skip = moved.nodes.find((n) => n.id === "skip")!;
    expect(skip.x).toBe(autoSkip.x);
    expect(skip.y).toBe(autoSkip.y);
  });

  it("does not mutate the input layout", () => {
    const auto = baseLayout();
    const before = auto.nodes.find((n) => n.id === "hit")!.x;
    applyManualPositions(auto, { hit: { x: 900, y: 700 } });
    expect(auto.nodes.find((n) => n.id === "hit")!.x).toBe(before);
  });

  it("re-hangs the edges on the moved box", () => {
    const moved = applyManualPositions(baseLayout(), { hit: { x: 900, y: 700 } });
    const edge = moved.edges.find((e) => e.to === "hit")!;
    expect(edge.toX).toBe(900 + NODE_WIDTH / 2);
    expect(edge.toY).toBe(700);

    const root = moved.nodes.find((n) => n.id === "root")!;
    expect(edge.fromX).toBe(root.x + NODE_WIDTH / 2);
    expect(edge.fromY).toBe(root.y + NODE_HEIGHT);
  });

  it("grows the bounding box so a box dragged far out still exports", () => {
    const moved = applyManualPositions(baseLayout(), { hit: { x: 1500, y: 1200 } });
    expect(moved.width).toBeGreaterThan(1500 + NODE_WIDTH);
    expect(moved.height).toBeGreaterThan(1200 + NODE_HEIGHT);
  });

  it("skips a stored position whose coordinates are not finite", () => {
    const auto = baseLayout();
    const autoHit = auto.nodes.find((n) => n.id === "hit")!;
    const moved = applyManualPositions(auto, {
      hit: { x: Number.NaN, y: 5 },
      skip: { x: 400, y: 400 },
    });
    expect(moved.nodes.find((n) => n.id === "hit")!.x).toBe(autoHit.x);
    expect(moved.nodes.find((n) => n.id === "skip")!.x).toBe(400);
  });

  it("returns an empty layout unchanged", () => {
    const empty = layoutTree(null);
    expect(applyManualPositions(empty, { a: { x: 1, y: 1 } })).toBe(empty);
  });
});

describe("clampCanvasHeight", () => {
  it("holds the height inside the allowed band and rounds", () => {
    expect(clampCanvasHeight(10)).toBe(MIN_CANVAS_HEIGHT);
    expect(clampCanvasHeight(99999)).toBe(MAX_CANVAS_HEIGHT);
    expect(clampCanvasHeight(640.4)).toBe(640);
    expect(clampCanvasHeight(Number.NaN)).toBe(DEFAULT_CANVAS_HEIGHT);
  });
});

describe("prunePositions", () => {
  it("drops entries for ids that are gone", () => {
    const pruned = prunePositions({ a: { x: 1, y: 2 }, b: { x: 3, y: 4 } }, ["a"]);
    expect(pruned).toEqual({ a: { x: 1, y: 2 } });
  });
});

describe("normalizePrefs", () => {
  it("keeps only finite (x, y) pairs", () => {
    const prefs = normalizePrefs({
      height: 700,
      positions: {
        ok: { x: 1, y: 2 },
        notAnObject: 7,
        missingY: { x: 1 },
        infinite: { x: 1, y: Number.POSITIVE_INFINITY },
        stringy: { x: "10", y: "20" },
      },
    });
    expect(prefs.positions).toEqual({ ok: { x: 1, y: 2 } });
    expect(prefs.height).toBe(700);
  });

  it("falls back to defaults for junk", () => {
    expect(normalizePrefs(null)).toEqual({ positions: {}, height: DEFAULT_CANVAS_HEIGHT });
    expect(normalizePrefs("nope")).toEqual({ positions: {}, height: DEFAULT_CANVAS_HEIGHT });
    expect(normalizePrefs({ positions: [] }).positions).toEqual({});
  });
});

describe("loadCanvasPrefs / saveCanvasPrefs", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
  });

  it("round-trips through localStorage", () => {
    saveCanvasPrefs("mango_x_v1", { positions: { hit: { x: 12, y: 34 } }, height: 700 });
    const loaded = loadCanvasPrefs("mango_x_v1");
    expect(loaded.positions).toEqual({ hit: { x: 12, y: 34 } });
    expect(loaded.height).toBe(700);
  });

  it("prunes deleted nodes on write", () => {
    saveCanvasPrefs(
      "mango_x_v1",
      { positions: { hit: { x: 1, y: 2 }, gone: { x: 3, y: 4 } }, height: 560 },
      ["hit"],
    );
    expect(loadCanvasPrefs("mango_x_v1").positions).toEqual({ hit: { x: 1, y: 2 } });
  });

  it("keeps trees apart", () => {
    saveCanvasPrefs("tree_a", { positions: { n: { x: 1, y: 1 } }, height: 560 });
    expect(loadCanvasPrefs("tree_b").positions).toEqual({});
  });

  it("returns defaults when nothing is stored", () => {
    expect(loadCanvasPrefs("never_saved")).toEqual({
      positions: {},
      height: DEFAULT_CANVAS_HEIGHT,
    });
  });

  it("returns defaults when the stored record is not JSON", () => {
    window.localStorage.setItem("ap.dt.canvas.v1.broken", "{not json");
    expect(loadCanvasPrefs("broken").positions).toEqual({});
  });

  it("does not throw when storage is blocked", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });
    expect(() => saveCanvasPrefs("t", { positions: {}, height: 560 })).not.toThrow();
    expect(loadCanvasPrefs("t").height).toBe(DEFAULT_CANVAS_HEIGHT);
  });

  it("does nothing without a tree id", () => {
    expect(() => saveCanvasPrefs("", { positions: {}, height: 560 })).not.toThrow();
    expect(loadCanvasPrefs("").positions).toEqual({});
  });
});

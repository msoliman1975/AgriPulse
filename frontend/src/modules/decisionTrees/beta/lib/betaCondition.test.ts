import { describe, expect, it } from "vitest";

import {
  appendChild,
  condShape,
  defaultGroup,
  defaultTerm,
  groupChildren,
  groupMode,
  nodeAt,
  operandListText,
  parseOperand,
  parseOperandList,
  replaceAt,
  termLeft,
  withGroupMode,
  withOp,
  type CondNode,
} from "./betaCondition";

describe("condShape", () => {
  it("reads each shape by the key it carries, as the evaluator does", () => {
    expect(condShape(undefined)).toBe("empty");
    expect(condShape(null)).toBe("empty");
    expect(condShape({ all_of: [] })).toBe("group");
    expect(condShape({ any_of: [] })).toBe("group");
    expect(condShape({ not: { op: "lt", left: {}, right: 1 } })).toBe("not");
    expect(condShape({ op: "between", left: {}, low: 1, high: 2 })).toBe("term");
  });

  it("calls an operator the engine does not implement unknown", () => {
    expect(condShape({ op: "matches", left: {}, right: "x" })).toBe("unknown");
    expect(condShape("lt")).toBe("unknown");
  });
});

describe("withOp", () => {
  it("turns one value into a range, keeping the number the author typed", () => {
    const next = withOp({ op: "lt", left: { source: "indices" }, right: 0.4 }, "between");
    expect(next).toEqual({ op: "between", left: { source: "indices" }, low: 0.4, high: 0.4 });
  });

  it("turns a range back into one value, taking the low bound", () => {
    const next = withOp({ op: "between", left: { source: "vars" }, low: 3, high: 9 }, "ge");
    expect(next).toEqual({ op: "ge", left: { source: "vars" }, right: 3 });
  });

  it("drops the key the old operator owned, so a term never names two", () => {
    const next = withOp({ op: "between", left: {}, low: 1, high: 2 }, "in");
    expect(Object.keys(next).sort()).toEqual(["left", "op", "values"]);
  });

  it("keeps the left reading across every change", () => {
    const left = { source: "findings", code: "dry", key: "registered" };
    for (const op of ["lt", "between", "in", "eq"] as const) {
      expect(withOp({ op: "lt", left, right: 1 }, op).left).toEqual(left);
    }
  });
});

describe("termLeft", () => {
  it("falls back to a readable default rather than to nothing", () => {
    expect(termLeft({ op: "lt", right: 1 }).source).toBe("indices");
  });
});

describe("groups", () => {
  it("keeps the children when the mode changes", () => {
    const group = defaultGroup("all_of");
    const flipped = withGroupMode(group, "any_of");
    expect(groupMode(flipped)).toBe("any_of");
    expect(groupChildren(flipped)).toEqual(groupChildren(group));
  });

  it("appends a child to the group the path names", () => {
    const tree = { all_of: [defaultTerm(), defaultGroup("any_of")] };
    const next = appendChild(tree, [1], defaultTerm()) as CondNode;
    expect(groupChildren(groupChildren(next)[1] as CondNode)).toHaveLength(2);
  });
});

describe("replaceAt", () => {
  const tree = (): CondNode => ({
    all_of: [
      { op: "lt", left: { source: "indices" }, right: 0 },
      { any_of: [{ op: "gt", left: { source: "block" }, right: 5 }] },
    ],
  });

  it("replaces one child and leaves its siblings alone", () => {
    const next = replaceAt(tree(), [0], {
      op: "ge",
      left: { source: "vars" },
      right: 2,
    }) as CondNode;
    expect(groupChildren(next)[0]).toEqual({ op: "ge", left: { source: "vars" }, right: 2 });
    expect(groupChildren(next)[1]).toEqual(groupChildren(tree())[1]);
  });

  it("removes a child when the replacement is null", () => {
    const next = replaceAt(tree(), [0], null) as CondNode;
    expect(groupChildren(next)).toHaveLength(1);
  });

  it("drops a group that has lost its last child, rather than leaving an empty one", () => {
    // `all_of: []` matches every cell and `any_of: []` matches none. Neither
    // is what removing the last test means.
    const next = replaceAt(tree(), [1, 0], null) as CondNode;
    expect(groupChildren(next)).toHaveLength(1);
    expect(condShape(groupChildren(next)[0])).toBe("term");
  });

  it("empties the condition when the root goes", () => {
    expect(replaceAt(tree(), [], null)).toBeUndefined();
  });

  it("reaches through a not wrapper", () => {
    const wrapped = { not: { op: "lt", left: {}, right: 1 } };
    const next = replaceAt(wrapped, [0], { op: "gt", left: {}, right: 9 }) as CondNode;
    expect(next).toEqual({ not: { op: "gt", left: {}, right: 9 } });
  });

  it("leaves the tree alone for a path that leads nowhere", () => {
    expect(replaceAt(tree(), [7], defaultTerm())).toEqual(tree());
  });
});

describe("nodeAt", () => {
  it("finds a nested child", () => {
    const tree = { all_of: [defaultTerm(), { any_of: [{ op: "eq", left: {}, right: "a" }] }] };
    expect(nodeAt(tree, [1, 0])).toEqual({ op: "eq", left: {}, right: "a" });
  });

  it("returns null past the end of a group", () => {
    expect(nodeAt({ all_of: [defaultTerm()] }, [4])).toBeNull();
  });
});

describe("operands", () => {
  it("keeps a number a number, so the comparison is numeric", () => {
    expect(parseOperand("0.35")).toBe(0.35);
    expect(parseOperand("-2")).toBe(-2);
  });

  it("reads true and false back as booleans", () => {
    expect(parseOperand("true")).toBe(true);
    expect(parseOperand("false")).toBe(false);
  });

  it("leaves anything else as text", () => {
    expect(parseOperand("sandy loam")).toBe("sandy loam");
    expect(parseOperand("  ")).toBe("");
  });

  it("splits a list on commas and types each part", () => {
    expect(parseOperandList("1, 2, three")).toEqual([1, 2, "three"]);
    expect(parseOperandList(" , ")).toEqual([]);
  });

  it("reads a list back the way it was typed", () => {
    expect(operandListText([1, "two"])).toBe("1, two");
    expect(operandListText("not a list")).toBe("");
  });
});

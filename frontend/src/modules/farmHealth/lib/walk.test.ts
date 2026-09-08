import { describe, expect, it } from "vitest";

import type { WalkStep } from "@/api/farmHealth";
import { readText, sharedPrefix, testText, walkRows } from "./walk";

const CWSI_STEP: WalkStep = {
  node_id: "medium_check",
  matched: true,
  label_en: "Is CWSI above the medium-tree bound?",
  label_ar: "هل CWSI فوق حدّ الشجرة المتوسطة؟",
  condition: {
    tree: {
      op: "gt",
      left: { source: "indices", index_code: "cwsi", key: "mean" },
      right: { source: "params", name: "medium_cwsi_ceiling" },
    },
  },
  values: { "indices.cwsi.mean": "0.47" },
};

describe("testText", () => {
  it("reads a comparison as an operator and a threshold", () => {
    expect(testText(CWSI_STEP.condition)).toBe("> medium_cwsi_ceiling");
  });

  it("spells the operators the tree language uses", () => {
    // `ge` and `gte` both appear in the seeds. An unknown operator compiles
    // and runs silently in this system, so the screen must not hide one.
    expect(testText({ tree: { op: "ge", right: 0.99 } })).toBe("≥ 0.99");
    expect(testText({ tree: { op: "gte", right: 0.99 } })).toBe("≥ 0.99");
    expect(testText({ tree: { op: "weird_op", right: 1 } })).toBe("weird_op 1");
  });

  it("joins the parts of an all_of", () => {
    const condition = {
      tree: {
        all_of: [
          { op: "eq", left: { source: "crop_attribute", code: "bearing_status" }, right: "bearing" },
          { op: "in", left: { source: "block", field: "growth_stage" }, values: ["maturation"] },
        ],
      },
    };

    expect(testText(condition)).toBe("= bearing and in maturation");
  });

  it("returns null rather than half a phrase", () => {
    // A test rendered without its operator reads as a fact rather than a
    // comparison, which is worse than showing no test at all.
    expect(testText({ tree: { left: { source: "indices", index_code: "ndvi" } } })).toBeNull();
    expect(testText(null)).toBeNull();
    expect(testText("nonsense")).toBeNull();
  });
});

describe("readText", () => {
  it("shows the path and the value the tree resolved", () => {
    expect(readText(CWSI_STEP)).toBe("indices.cwsi.mean = 0.47");
  });

  it("says a ref resolved to nothing, rather than printing null", () => {
    // A null here is a fail-closed miss, not a zero, and the two lead to
    // different conclusions.
    expect(readText({ ...CWSI_STEP, values: { "indices.ndvi.mean": null } })).toBe(
      "indices.ndvi.mean = no reading",
    );
  });

  it("is null when the node read nothing", () => {
    expect(readText({ ...CWSI_STEP, values: {} })).toBeNull();
    expect(readText({ ...CWSI_STEP, values: null })).toBeNull();
  });
});

describe("walkRows", () => {
  it("turns a step into a question, a reading, a test and an answer", () => {
    const [row] = walkRows([CWSI_STEP], false);

    expect(row).toEqual({
      nodeId: "medium_check",
      question: "Is CWSI above the medium-tree bound?",
      read: "indices.cwsi.mean = 0.47",
      test: "> medium_cwsi_ceiling",
      matched: true,
    });
  });

  it("takes the Arabic label when the reader is on Arabic", () => {
    expect(walkRows([CWSI_STEP], true)[0].question).toBe("هل CWSI فوق حدّ الشجرة المتوسطة؟");
  });

  it("falls back to the node id when the tree gave no label", () => {
    const bare: WalkStep = { node_id: "size_small", matched: false };
    expect(walkRows([bare], false)[0].question).toBe("size_small");
  });
});

describe("sharedPrefix", () => {
  const rows = (ids: string[], matched: boolean[]) =>
    ids.map((id, i) => ({
      nodeId: id,
      question: id,
      read: null,
      test: null,
      matched: matched[i],
    }));

  it("is zero for a single walk, which shares nothing with itself", () => {
    expect(sharedPrefix([rows(["a", "b"], [false, true])])).toBe(0);
  });

  it("counts the opening steps two walks agree on", () => {
    const a = rows(["floor", "band"], [false, true]);
    const b = rows(["floor", "band", "baseline"], [false, false, true]);

    // They agree on `floor` and part on `band`.
    expect(sharedPrefix([a, b])).toBe(1);
  });

  it("stops at the first step whose answer differs, not just its name", () => {
    const a = rows(["floor"], [true]);
    const b = rows(["floor"], [false]);

    expect(sharedPrefix([a, b])).toBe(0);
  });
});

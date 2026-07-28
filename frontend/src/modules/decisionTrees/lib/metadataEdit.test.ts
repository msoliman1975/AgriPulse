import { describe, expect, it } from "vitest";
import jsYaml from "js-yaml";

import { applyTreeMetaToYaml, readTreeMeta } from "./metadataEdit";

const SAMPLE = `code: my_tree
name_en: Original name
name_ar: الاسم الأصلي
description_en: Original description
root: root
nodes:
  root:
    outcome:
      action_type: no_action
      text_en: noop
`;

describe("readTreeMeta", () => {
  it("reads the top-level name/description keys", () => {
    const meta = readTreeMeta(SAMPLE);
    expect(meta.name_en).toBe("Original name");
    expect(meta.name_ar).toBe("الاسم الأصلي");
    expect(meta.description_en).toBe("Original description");
    // description_ar absent → empty string, not undefined.
    expect(meta.description_ar).toBe("");
  });

  it("tolerates null / empty / unparseable input", () => {
    const empty = { name_en: "", name_ar: "", description_en: "", description_ar: "" };
    expect(readTreeMeta(null)).toEqual(empty);
    expect(readTreeMeta("")).toEqual(empty);
    expect(readTreeMeta(":\n  : bad: [")).toEqual(empty);
  });
});

describe("applyTreeMetaToYaml", () => {
  it("round-trips an edited name back through readTreeMeta", () => {
    const next = applyTreeMetaToYaml(SAMPLE, { name_en: "Renamed" });
    expect(readTreeMeta(next).name_en).toBe("Renamed");
  });

  it("clears an emptied optional field to null (absent)", () => {
    const next = applyTreeMetaToYaml(SAMPLE, { name_ar: "" });
    expect(readTreeMeta(next).name_ar).toBe("");
    // Stored as an explicit null so the loader treats it as absent.
    const doc = jsYaml.load(next) as Record<string, unknown>;
    expect(doc.name_ar).toBeNull();
  });

  it("preserves the structural body (root + nodes)", () => {
    const next = applyTreeMetaToYaml(SAMPLE, {
      name_en: "New",
      description_en: "New desc",
    });
    const doc = jsYaml.load(next) as Record<string, unknown>;
    expect(doc.root).toBe("root");
    expect(doc.nodes).toHaveProperty("root");
    expect(doc.code).toBe("my_tree");
  });

  it("leaves unspecified fields untouched", () => {
    const next = applyTreeMetaToYaml(SAMPLE, { description_en: "Only desc changed" });
    const meta = readTreeMeta(next);
    expect(meta.name_en).toBe("Original name");
    expect(meta.description_en).toBe("Only desc changed");
  });
});

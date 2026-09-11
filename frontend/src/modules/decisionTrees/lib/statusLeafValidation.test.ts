import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { validateTreeStructure } from "./treeStructure";

/**
 * The editor's structural check must agree with what the platform ships.
 *
 * It did not. Every leaf was required to carry an `action_type`, and a status
 * leaf has none — an action type is what a person does about a finding, and a
 * status leaf asks for nothing. So opening any of the 33 shipped trees showed
 * "Structural issues — save is blocked" and named a field that kind of leaf
 * is not supposed to have. Every one of the 63 rewritten leaves was affected.
 *
 * The last test reads the real shipped bodies rather than a fixture. A fixture
 * would have passed the whole time this was broken.
 *
 * Those bodies used to be YAML files under the backend's `seeds/` directory.
 * They are database rows now — public migration 0085 carried them over and the
 * files are gone — so this reads the migration's data file, which holds each
 * tree's YAML exactly as it shipped. Note what that means: this guards what a
 * fresh database installs, not what production is running today, because a
 * platform admin edits those in the app.
 */

const SHIPPED_TREES = path.resolve(
  __dirname,
  "../../../../../backend/migrations/public/versions/data/0085_platform_decision_trees.json",
);

const BASE = `
code: probe_v1
name_en: Probe
root: root
nodes:
  root:
    condition:
      tree: { op: lt, left: { source: indices, index_code: ndvi, key: mean }, right: 0.4 }
    on_match: leaf_a
    on_miss: leaf_b
  leaf_b:
    outcome:
      kind: status
      status: good
      text_en: Fine.
`;

function withLeafA(outcome: string): string {
  return `${BASE}  leaf_a:\n    outcome:\n${outcome}`;
}

function messages(yaml: string): string[] {
  return validateTreeStructure(yaml).map((e) => e.message);
}

describe("a status leaf is not missing anything", () => {
  it("does not ask a status leaf for an action type", () => {
    const errors = messages(
      withLeafA("      kind: status\n      status: na\n      text_en: No reading.\n"),
    );

    expect(errors).toEqual([]);
  });

  it("does not ask a no-action leaf for an action type", () => {
    const errors = messages(withLeafA("      kind: no_action\n      action_type: no_action\n"));

    expect(errors).toEqual([]);
  });

  it("reads an old quiet branch as no action, so it is not asked either", () => {
    // `kind: recommendation` next to `action_type: no_action` — the shape 15
    // of the shipped leaves used before the rewrite.
    const errors = messages(
      withLeafA("      kind: recommendation\n      action_type: no_action\n      text_en: ok\n"),
    );

    expect(errors).toEqual([]);
  });

  it("still asks a recommendation and an alert for one", () => {
    expect(messages(withLeafA("      kind: recommendation\n      text_en: ok\n"))).toEqual([
      "Leaf outcome is missing `action_type`.",
    ]);
    expect(
      messages(withLeafA("      kind: alert\n      severity: warning\n      text_en: ok\n")),
    ).toEqual(["Leaf outcome is missing `action_type`."]);
  });
});

describe("what the editor catches before the publish does", () => {
  it("a status leaf with no status", () => {
    const errors = messages(withLeafA("      kind: status\n      text_en: ok\n"));

    expect(errors).toEqual(["Status leaf is missing `status` — pick one before saving."]);
  });

  it("a status the platform does not have", () => {
    const errors = messages(withLeafA("      kind: status\n      status: gud\n      text_en: ok\n"));

    expect(errors[0]).toContain("Status must be one of");
    expect(errors[0]).toContain("gud");
  });

  it("a status on a leaf that asks for work", () => {
    // The loader refuses this: an alert declaring `good` would paint itself
    // green while opening a red card.
    const errors = messages(
      withLeafA(
        "      kind: alert\n      action_type: scout\n      severity: warning\n" +
          "      status: good\n      text_en: ok\n",
      ),
    );

    expect(errors).toEqual(["Only a status leaf may set `status` — this leaf is a alert."]);
  });

  it("a kind that does not exist", () => {
    const errors = messages(
      withLeafA("      kind: verdict\n      action_type: scout\n      text_en: ok\n"),
    );

    expect(errors[0]).toContain("Leaf `kind` must be one of");
  });
});

describe("every shipped tree opens without a structural error", () => {
  const trees: { code: string; tree_yaml: string }[] = JSON.parse(
    fs.readFileSync(SHIPPED_TREES, "utf-8"),
  );

  it("finds the shipped trees", () => {
    expect(trees.length).toBe(33);
  });

  it.each(trees.map((t) => [t.code, t.tree_yaml] as const))("%s", (_code, yaml) => {
    expect(validateTreeStructure(yaml)).toEqual([]);
  });
});

/**
 * The shipped `mango_unified` body, read by the designer's own checks.
 *
 * The backend test beside it proves the server compiles it. This one proves
 * the screen agrees: the editor hints are what an author sees before they ever
 * press Save, and a body that the server accepts while the canvas flags it is
 * the drift `betaCompile.ts` exists to catch.
 */

import { describe, expect, it } from "vitest";

import definition from "../../../../../../docs/trees/mango_unified.definition.json";
import { betaEditorHints } from "./betaCompile";
import { layoutBetaTree } from "./betaLayout";
import { dumpBetaDoc, readRegisters, type BetaTreeDoc } from "./betaTree";

const doc = definition as unknown as BetaTreeDoc;

describe("mango_unified in the designer", () => {
  it("raises no editor hint", () => {
    const hints = betaEditorHints({
      yaml: dumpBetaDoc(doc),
      knownFindingCodes: readRegisters(doc),
    });
    expect(hints.map((h) => `${h.rule} ${h.node_id ?? ""}`)).toEqual([]);
  });

  it("lays out every node once", () => {
    const layout = layoutBetaTree(doc);
    expect(layout.nodes).toHaveLength(Object.keys(doc.nodes ?? {}).length);
    expect(new Set(layout.nodes.map((n) => n.id)).size).toBe(layout.nodes.length);
  });

  it("ends on one stop, which every route reaches", () => {
    const layout = layoutBetaTree(doc);
    const stops = layout.nodes.filter((n) => n.kind === "stop");
    expect(stops).toHaveLength(1);
    expect(stops[0].shape).toBe("circle");
  });
});

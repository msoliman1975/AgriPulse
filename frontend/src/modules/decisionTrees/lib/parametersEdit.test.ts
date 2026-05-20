import { describe, expect, it } from "vitest";

import {
  applyParameterEditsToYaml,
  hasParameterEdits,
  validateParameterDeclaration,
} from "./parametersEdit";

const _BASE = `code: demo
name_en: Demo
parameters:
  existing_threshold:
    type: number
    default: -0.15
    min: -0.5
    max: 0
root: leaf
nodes:
  leaf:
    outcome:
      action_type: no_action
      text_en: ok
`;

const _NO_PARAMS_YAML = `code: demo
name_en: Demo
root: leaf
nodes:
  leaf:
    outcome:
      action_type: no_action
      text_en: ok
`;

describe("hasParameterEdits", () => {
  it("returns false for an empty buffer", () => {
    expect(hasParameterEdits({})).toBe(false);
  });
  it("returns true for any pending change including deletes", () => {
    expect(hasParameterEdits({ x: null })).toBe(true);
    expect(
      hasParameterEdits({ x: { type: "number", default: 1 } }),
    ).toBe(true);
  });
});

describe("validateParameterDeclaration", () => {
  it("accepts a well-formed number declaration", () => {
    expect(
      validateParameterDeclaration("foo", {
        type: "number",
        default: 0.5,
        min: 0,
        max: 1,
      }),
    ).toBeNull();
  });
  it("rejects an enum without values", () => {
    expect(
      validateParameterDeclaration("foo", {
        type: "enum",
        default: "a",
      }),
    ).toMatch(/non-empty values/);
  });
  it("rejects an enum default not in values", () => {
    expect(
      validateParameterDeclaration("foo", {
        type: "enum",
        default: "c",
        values: ["a", "b"],
      }),
    ).toMatch(/one of values/);
  });
  it("rejects a number default outside min/max", () => {
    expect(
      validateParameterDeclaration("foo", {
        type: "number",
        default: 5,
        min: 0,
        max: 1,
      }),
    ).toMatch(/≤ 1/);
  });
  it("rejects an integer default that's a float", () => {
    expect(
      validateParameterDeclaration("foo", {
        type: "integer",
        default: 1.5,
      }),
    ).toMatch(/integer/);
  });
  it("rejects an invalid identifier name", () => {
    expect(
      validateParameterDeclaration("has-dash", {
        type: "number",
        default: 0,
      }),
    ).toMatch(/alphanumeric/);
  });
});

describe("applyParameterEditsToYaml", () => {
  it("upserts a new parameter into a tree that already has a parameters block", () => {
    const out = applyParameterEditsToYaml(_BASE, {
      new_param: { type: "integer", default: 24 },
    });
    expect(out).toContain("new_param");
    expect(out).toContain("type: integer");
    // Existing parameter survives.
    expect(out).toContain("existing_threshold");
  });

  it("creates the parameters block when the tree had none", () => {
    const out = applyParameterEditsToYaml(_NO_PARAMS_YAML, {
      first: { type: "string", default: "hello" },
    });
    expect(out).toContain("parameters:");
    expect(out).toContain("first:");
    expect(out).toContain("default: hello");
  });

  it("deletes a parameter when the buffer value is null", () => {
    const out = applyParameterEditsToYaml(_BASE, {
      existing_threshold: null,
    });
    // Block goes away entirely because it was the only parameter.
    expect(out).not.toContain("existing_threshold");
    expect(out).not.toMatch(/^parameters:/m);
  });

  it("drops optional fields when they're null so the YAML stays clean", () => {
    const out = applyParameterEditsToYaml(_NO_PARAMS_YAML, {
      x: {
        type: "number",
        default: 1,
        min: null,
        max: null,
        description: null,
      },
    });
    expect(out).toContain("default: 1");
    expect(out).not.toContain("min:");
    expect(out).not.toContain("max:");
    expect(out).not.toContain("description:");
  });

  it("writes enum values as a YAML list", () => {
    const out = applyParameterEditsToYaml(_NO_PARAMS_YAML, {
      phase: {
        type: "enum",
        default: "flowering",
        values: ["pre", "flowering", "post"],
      },
    });
    expect(out).toContain("type: enum");
    expect(out).toContain("default: flowering");
    expect(out).toMatch(/values:\s*\n\s*- pre/);
  });

  it("returns input unchanged when the buffer is empty", () => {
    expect(applyParameterEditsToYaml(_BASE, {})).toBe(_BASE);
  });
});

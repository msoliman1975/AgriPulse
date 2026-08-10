import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { ACTION_TYPES, ACTION_TYPE_GROUP_ORDER, isActionType } from "@/lib/actionTypes";

/**
 * Lock-step with the backend.
 *
 * A mirrored constant that drifts degrades the UI with no error — the tree
 * editor would offer a verb the CHECK constraint rejects, or omit one the
 * engine can emit, and either way nothing fails until a user hits it. So the
 * test reads the backend's own source rather than a copy of it.
 */
const BACKEND_SCHEMAS = join(__dirname, "../../../backend/app/modules/recommendations/schemas.py");
const MIGRATION_0015 = join(
  __dirname,
  "../../../backend/migrations/tenant/versions/0015_recommendations.py",
);

function backendLiteral(): string[] {
  const src = readFileSync(BACKEND_SCHEMAS, "utf8");
  const block = /ActionType = Literal\[([\s\S]*?)\]/.exec(src);
  if (block === null) throw new Error("ActionType Literal not found in backend schemas.py");
  return [...block[1].matchAll(/"([a-z_]+)"/g)].map((m) => m[1]);
}

function checkConstraint(): string[] {
  const src = readFileSync(MIGRATION_0015, "utf8");
  const block = /action_type IN \(([\s\S]*?)\)"?\s*\)/.exec(src);
  if (block === null) throw new Error("action_type CHECK not found in migration 0015");
  return [...block[1].matchAll(/'([a-z_]+)'/g)].map((m) => m[1]);
}

describe("ACTION_TYPES", () => {
  it("matches the backend ActionType Literal exactly", () => {
    expect([...ACTION_TYPES].sort()).toEqual(backendLiteral().sort());
  });

  it("matches the persisted CHECK constraint exactly", () => {
    // The CHECK is what actually rejects a bad value at write time; the
    // Literal only guards the API surface. Both have to agree with the UI.
    expect([...ACTION_TYPES].sort()).toEqual(checkConstraint().sort());
  });

  it("orders groups by field workflow and covers every actionable verb", () => {
    // no_action is deliberately absent — the engine writes no row for it, so
    // it can never appear as a group in the queue.
    expect(ACTION_TYPE_GROUP_ORDER).not.toContain("no_action");
    const missing = ACTION_TYPES.filter(
      (a) => a !== "no_action" && !ACTION_TYPE_GROUP_ORDER.includes(a),
    );
    expect(missing).toEqual([]);
  });

  it("recognises members and rejects typos", () => {
    expect(isActionType("spray")).toBe(true);
    // The failure the free-text box allowed: a clean save, then a 500 at
    // persist when the CHECK rejected it.
    expect(isActionType("sparying")).toBe(false);
    expect(isActionType("")).toBe(false);
  });
});

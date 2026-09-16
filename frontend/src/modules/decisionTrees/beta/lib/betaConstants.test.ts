import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  ACTION_TYPES,
  FINDING_SEVERITIES,
  FINDING_STATUSES,
  findingSetKey,
  worstSeverity,
  worstStatus,
} from "./betaConstants";

/**
 * Lock-step with the backend.
 *
 * Modelled on `lib/actionTypes.test.ts`, and for the same reason: a copy of a
 * backend list drifts with no error. These read the backend's own source
 * rather than a second copy of the values.
 */
const REPO_ROOT = join(__dirname, "../../../../../..");
const BACKEND_SCHEMAS = join(REPO_ROOT, "backend/app/modules/recommendations/schemas.py");
const FINDINGS_MIGRATION_DIR = join(REPO_ROOT, "backend/migrations/public/versions");

function backendSeverityLiteral(): string[] {
  const src = readFileSync(BACKEND_SCHEMAS, "utf8");
  const block = /Severity = Literal\[([\s\S]*?)\]/.exec(src);
  if (block === null) throw new Error("Severity Literal not found in backend schemas.py");
  return [...block[1].matchAll(/"([a-z_]+)"/g)].map((m) => m[1]);
}

/**
 * The `default_status` CHECK on `public.decision_tree_findings`.
 *
 * Session 1 of the beta engine adds that table. Until its migration is on this
 * branch there is nothing to compare against, so the assertion below is
 * reported as skipped rather than passing on an absent file — a check that
 * cannot fail is not evidence. Delete the guard when the migration lands.
 */
function findingsStatusCheck(): string[] | null {
  if (!existsSync(FINDINGS_MIGRATION_DIR)) return null;
  for (const name of readdirSync(FINDINGS_MIGRATION_DIR)) {
    if (!name.endsWith(".py")) continue;
    const src = readFileSync(join(FINDINGS_MIGRATION_DIR, name), "utf8");
    if (!src.includes("decision_tree_findings")) continue;
    const block = /default_status IN \(([\s\S]*?)\)/.exec(src);
    if (block === null) continue;
    return [...block[1].matchAll(/'([a-z_]+)'/g)].map((m) => m[1]);
  }
  return null;
}

const statusCheck = findingsStatusCheck();

describe("FINDING_SEVERITIES", () => {
  it("matches the backend Severity Literal exactly", () => {
    expect([...FINDING_SEVERITIES].sort()).toEqual(backendSeverityLiteral().sort());
  });
});

describe("FINDING_STATUSES", () => {
  it.skipIf(statusCheck === null)(
    "matches the decision_tree_findings default_status CHECK exactly",
    () => {
      expect([...FINDING_STATUSES].sort()).toEqual([...(statusCheck ?? [])].sort());
    },
  );
});

describe("ACTION_TYPES", () => {
  it("is the shared list, not a second copy", async () => {
    const shared = await import("@/lib/actionTypes");
    expect(ACTION_TYPES).toBe(shared.ACTION_TYPES);
  });
});

describe("folding helpers", () => {
  it("takes the highest severity", () => {
    expect(worstSeverity(["info", "critical", "warning"])).toBe("critical");
    expect(worstSeverity([])).toBeNull();
  });

  it("takes the worst status, and calls an empty set normal", () => {
    expect(worstStatus(["normal", "stressed", "watch"])).toBe("stressed");
    expect(worstStatus(["normal", "unknown"])).toBe("unknown");
    expect(worstStatus([])).toBe("normal");
  });

  it("keys a finding set by its sorted codes, ignoring order and repeats", () => {
    expect(findingSetKey(["ndvi_low", "dry", "dry"])).toBe("dry+ndvi_low");
    expect(findingSetKey(["dry", "ndvi_low"])).toBe(findingSetKey(["ndvi_low", "dry"]));
  });
});

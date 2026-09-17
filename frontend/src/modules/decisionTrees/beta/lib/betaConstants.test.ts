import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  ACTION_TYPES,
  EMPTY_SET_STATUS,
  FINDING_SEVERITIES,
  FINDING_STATUSES,
  STATUS_RANK,
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
 *
 * This matters more here than usual. The design prompt named
 * `normal | watch | stressed | unknown` for the finding status; the catalogue
 * that shipped uses the platform's five decision-tree status codes, and the
 * CHECK on `decision_tree_findings.default_status` rejects the other four. A
 * test that reads the backend list is what catches that, and it is why this
 * one is not allowed to skip.
 */
const REPO_ROOT = join(__dirname, "../../../../../..");
const BACKEND_SCHEMAS = join(REPO_ROOT, "backend/app/modules/recommendations/schemas.py");
const STATUS_CODES_PY = join(REPO_ROOT, "backend/app/modules/recommendations/status_codes.py");

function backendSeverityLiteral(): string[] {
  const src = readFileSync(BACKEND_SCHEMAS, "utf8");
  const block = /Severity = Literal\[([\s\S]*?)\]/.exec(src);
  if (block === null) throw new Error("Severity Literal not found in backend schemas.py");
  return [...block[1].matchAll(/"([a-z_]+)"/g)].map((m) => m[1]);
}

/** `StatusDefinition(code, rank, …)` rows, in declaration order. */
function backendStatusDefinitions(): Array<{ code: string; rank: number }> {
  const src = readFileSync(STATUS_CODES_PY, "utf8");
  const block = /STATUS_DEFINITIONS: tuple\[StatusDefinition, \.\.\.\] = \(([\s\S]*?)\n\)/.exec(
    src,
  );
  if (block === null) {
    throw new Error("STATUS_DEFINITIONS not found in backend status_codes.py");
  }
  return [...block[1].matchAll(/StatusDefinition\("([a-z_]+)",\s*(\d+)/g)].map((m) => ({
    code: m[1],
    rank: Number(m[2]),
  }));
}

describe("FINDING_SEVERITIES", () => {
  it("matches the backend Severity Literal exactly", () => {
    expect([...FINDING_SEVERITIES].sort()).toEqual(backendSeverityLiteral().sort());
  });
});

describe("FINDING_STATUSES", () => {
  it("matches the platform status codes exactly", () => {
    const backend = backendStatusDefinitions().map((d) => d.code);
    expect([...FINDING_STATUSES].sort()).toEqual([...backend].sort());
  });

  it("uses the platform ranks, so a fold and a block verdict order the same way", () => {
    // `findings.worst_status` ranks a fold with `StatusDefinition.rank`, and
    // a block's worst verdict uses the same number. A second ordering here
    // would colour a cell differently from the block it sits in.
    const backend = Object.fromEntries(backendStatusDefinitions().map((d) => [d.code, d.rank]));
    expect(STATUS_RANK).toEqual(backend);
  });

  it("is not the reports module's z-score vocabulary", () => {
    // The one mistake this list exists to prevent. Writing `stressed` into
    // `default_status` is a CHECK violation, not a display bug.
    for (const wrong of ["normal", "watch", "stressed", "unknown"]) {
      expect(FINDING_STATUSES as readonly string[]).not.toContain(wrong);
    }
  });
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

  it("takes the worst status", () => {
    expect(worstStatus(["good", "alert", "issue"])).toBe("alert");
    expect(worstStatus(["na", "good"])).toBe("good");
  });

  it("calls an empty set very_good, not na", () => {
    // The tree ran and nothing fired. `na` means no tree had an opinion,
    // which is a different answer. Matches `findings.worst_status`.
    expect(worstStatus([])).toBe("very_good");
    expect(EMPTY_SET_STATUS).toBe("very_good");
  });

  it("keys a finding set by its sorted codes, ignoring order and repeats", () => {
    expect(findingSetKey(["ndvi_low", "dry", "dry"])).toBe("dry+ndvi_low");
    expect(findingSetKey(["dry", "ndvi_low"])).toBe(findingSetKey(["ndvi_low", "dry"]));
  });
});

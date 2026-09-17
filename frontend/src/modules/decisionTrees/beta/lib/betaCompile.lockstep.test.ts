import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import en from "@/i18n/locales/en/decisionTreesBeta.json";

import { HINT_RULES, betaEditorHints } from "./betaCompile";

/**
 * Lock-step between the browser's editing hints and the server's compiler.
 *
 * `betaCompile.ts` is advisory: the server holds the publish. But a hint that
 * names a rule the compiler does not have is this frontend inventing an
 * opinion of its own, and that is exactly how two validators drift apart with
 * no error. So the rule names are one vocabulary, read here from the
 * compiler's own source rather than from a second copy of the list.
 *
 * The check is one-directional on purpose. Every hint rule must be a compiler
 * rule; a compiler rule with no hint is fine, because the server sends
 * `message_en` and `message_ar` with every error and the panel renders those.
 */
const REPO_ROOT = join(__dirname, "../../../../../..");
const COMPILER = join(REPO_ROOT, "backend/app/modules/recommendations/folding_compiler.py");

/**
 * Every `rule` the compiler can emit.
 *
 * It builds them through `errors.add(rule, message_en, message_ar, *nodes)`,
 * so the rule is the first argument of every call. Two call shapes exist —
 * the argument on the same line, and the argument on the line after — and
 * both are read.
 */
function compilerRules(): string[] | null {
  if (!existsSync(COMPILER)) return null;
  const src = readFileSync(COMPILER, "utf8");
  const found = [...src.matchAll(/errors\.add\(\s*"([a-z0-9-]+)"/g)].map((m) => m[1]);
  return found.length === 0 ? null : [...new Set(found)];
}

const rules = compilerRules();

/** One body that trips most of the rule list at once: a switch with no
 *  subject, no cases and no default; a register with no code and a bad
 *  severity pointing at a node that is not there; an outcome leaf beside
 *  them; and two combination rules, one empty and one naming a code the tree
 *  never registers. */
const BROKEN = `root: sw_1
nodes:
  sw_1:
    switch:
      cases: []
  reg_1:
    register: { severity: nonsense }
    next: gone
  cond_1:
    condition: { tree: { op: lt, left: 1, right: 2 } }
    outcome: { status: normal }
combinations:
  - codes: []
  - codes: [dry]
`;

describe("editor hint rules", () => {
  /**
   * Session A's compiler is on `feat/dte-compiler` and is not on this branch
   * yet. Until it lands there is nothing to compare against, so this reports
   * as skipped rather than passing on an absent file: a check that cannot
   * fail is not evidence. The guard goes when the branch merges.
   */
  it.skipIf(rules === null)("are all rules the backend compiler emits", () => {
    const unknown = HINT_RULES.filter((rule) => !(rules ?? []).includes(rule));
    expect(unknown).toEqual([]);
  });

  it("has English copy for every message a hint can carry", () => {
    const copy = en.publish.rule as Record<string, string>;
    const missing = betaEditorHints({ yaml: BROKEN, knownFindingCodes: [] })
      .map((hint) => hint.messageKey)
      .filter((key) => !(key in copy));
    expect([...new Set(missing)]).toEqual([]);
  });

  it("emits only declared rules on a body that breaks several at once", () => {
    const hints = betaEditorHints({ yaml: BROKEN, knownFindingCodes: [] });
    expect(hints.length).toBeGreaterThan(0);
    const declared: readonly string[] = HINT_RULES;
    expect(hints.filter((h) => !declared.includes(h.rule))).toEqual([]);
  });
});

// Copy parity for the beta designer.
//
// Modelled on `labs/console/consoleI18n.test.ts`, and for the same reason:
// i18next resolves a missing key to the key itself, so a rendered-text
// assertion passes on a typo. These read the bundles directly.
//
// Both directions matter. Missing Arabic is the obvious failure; a key that
// exists in Arabic and not English is the one that rots quietly.

import { describe, expect, it } from "vitest";

import ar from "@/i18n/locales/ar/decisionTreesBeta.json";
import en from "@/i18n/locales/en/decisionTreesBeta.json";
import arTrees from "@/i18n/locales/ar/decisionTrees.json";
import enTrees from "@/i18n/locales/en/decisionTrees.json";

import { ACTION_TYPES, FINDING_SEVERITIES, FINDING_STATUSES } from "./betaConstants";
import { BETA_NODE_KINDS, SWITCH_OPS } from "./betaTree";
import { BETA_VALUE_SOURCES } from "./betaValueRef";

const BUNDLES: [string, Record<string, unknown>][] = [
  ["en", en],
  ["ar", ar],
];

/** The five status labels are borrowed from the `decisionTrees` namespace
 *  rather than copied — see `lib/useStatusLabel.ts`. So they are checked
 *  there, in the bundle that actually has to carry them. */
const TREE_BUNDLES: [string, Record<string, unknown>][] = [
  ["en", enTrees as Record<string, unknown>],
  ["ar", arTrees as Record<string, unknown>],
];

function lookup(bundle: Record<string, unknown>, path: string): unknown {
  return path.split(".").reduce<unknown>((node, part) => {
    if (node && typeof node === "object" && part in (node as Record<string, unknown>)) {
      return (node as Record<string, unknown>)[part];
    }
    return undefined;
  }, bundle);
}

/** A plural key resolves as `key_one`, `key_other`, … rather than `key`. */
function hasString(bundle: Record<string, unknown>, path: string): boolean {
  if (typeof lookup(bundle, path) === "string") return true;
  const parts = path.split(".");
  const leaf = parts.pop()!;
  const parent = lookup(bundle, parts.join("."));
  if (!parent || typeof parent !== "object") return false;
  return Object.keys(parent).some(
    (k) => k.startsWith(`${leaf}_`) && typeof (parent as Record<string, unknown>)[k] === "string",
  );
}

/** Every leaf key, flattened, so the two bundles can be compared as sets.
 *  A plural suffix is stripped: Arabic has six forms and English two, and
 *  that difference is correct, not drift. */
function leafKeys(bundle: Record<string, unknown>, prefix = ""): Set<string> {
  const out = new Set<string>();
  for (const [key, value] of Object.entries(bundle)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (value && typeof value === "object" && !Array.isArray(value)) {
      for (const nested of leafKeys(value as Record<string, unknown>, path)) out.add(nested);
    } else {
      out.add(path.replace(/_(zero|one|two|few|many|other)$/, ""));
    }
  }
  return out;
}

/** Every rejection rule the compiler can emit. Kept here rather than exported
 *  from the union so a new rule with no copy fails this test. */
const REJECTION_RULES = [
  "yaml_unparsed",
  "missing_root",
  "unknown_root",
  "switch_without_default",
  "switch_default_unknown",
  "switch_case_no_target",
  "switch_no_cases",
  "switch_no_subject",
  "register_missing_code",
  "register_bad_severity",
  "register_not_declared",
  "register_unknown_code",
  "unreached_stop",
  "dangling_pointer",
  "empty_slot",
  "unreachable_node",
  "mixed_leaf_kinds",
  "combination_unknown_code",
  "combination_empty",
  "duplicate_combination",
] as const;

describe.each(BUNDLES)("decisionTreesBeta copy (%s)", (_lang, bundle) => {
  it("has a name for every node kind", () => {
    const missing = BETA_NODE_KINDS.filter((k) => !hasString(bundle, `canvas.kind.${k}`));
    expect(missing).toEqual([]);
  });

  it("has a label for every severity", () => {
    const missing = FINDING_SEVERITIES.filter((s) => !hasString(bundle, `severity.${s}`));
    expect(missing).toEqual([]);
  });

  it("carries no second copy of the status labels", () => {
    // They live in the `decisionTrees` namespace. A copy here would be five
    // more strings to keep in step, and the same block would read one way on
    // this screen and another on the map.
    expect(lookup(bundle, "status")).toBeUndefined();
  });

  it("has a label for every action type the backend can emit", () => {
    const missing = ACTION_TYPES.filter((a) => !hasString(bundle, `actionType.${a}`));
    expect(missing).toEqual([]);
  });

  it("has a label for every switch operator", () => {
    const missing = SWITCH_OPS.filter((op) => !hasString(bundle, `op.${op}`));
    expect(missing).toEqual([]);
  });

  it("has a name for every value-ref source", () => {
    const missing = BETA_VALUE_SOURCES.filter((s) => !hasString(bundle, `valueRef.sources.${s}`));
    expect(missing).toEqual([]);
  });

  it("has a message for every compiler rejection", () => {
    // Without this the publish panel would print the rule key at an author,
    // which is the one place the message has to be readable.
    const missing = REJECTION_RULES.filter((r) => !hasString(bundle, `publish.rule.${r}`));
    expect(missing).toEqual([]);
  });
});

describe.each(TREE_BUNDLES)("borrowed status labels (%s)", (_lang, bundle) => {
  it("has a label for every finding status", () => {
    const missing = FINDING_STATUSES.filter((s) => !hasString(bundle, `verdictStatus.${s}`));
    expect(missing).toEqual([]);
  });
});

describe("decisionTreesBeta bundles", () => {
  it("carries the same keys in both languages", () => {
    const enKeys = leafKeys(en as Record<string, unknown>);
    const arKeys = leafKeys(ar as Record<string, unknown>);
    expect([...enKeys].filter((k) => !arKeys.has(k)).sort()).toEqual([]);
    expect([...arKeys].filter((k) => !enKeys.has(k)).sort()).toEqual([]);
  });

  it("has no Arabic value left as its English original", () => {
    // A copied English string is the failure that looks translated. Codes and
    // punctuation-only values are exempt; nothing here is either.
    const enKeys = [...leafKeys(en as Record<string, unknown>)];
    const same = enKeys.filter((path) => {
      const e = lookup(en as Record<string, unknown>, path);
      const a = lookup(ar as Record<string, unknown>, path);
      return typeof e === "string" && typeof a === "string" && e.trim() !== "" && e === a;
    });
    expect(same).toEqual([]);
  });
});

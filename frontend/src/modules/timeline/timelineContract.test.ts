// What the frontend believes about the timeline API, checked against the
// API's own source.
//
// Frontend/backend constant drift on this platform is silent by
// construction: the screen keeps working, it just tells the reader
// something the server does not agree with. Here that would be a reader
// picking a 400-day window, watching the controls accept it, and getting a
// 422 they cannot act on — the message names a limit the picker never
// enforced.
//
// Source-level rather than behavioural on purpose. The defect is "someone
// changed the number in one file", which is exactly what reading both
// files catches, and which no amount of rendering would.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import ar from "@/i18n/locales/ar/timeline.json";
import en from "@/i18n/locales/en/timeline.json";
import { TIMELINE_EVENT_KINDS } from "@/api/timeline";
import { MAX_WINDOW_DAYS } from "./constants";
import { BLOCK_HIGHLIGHT_KINDS, MARK_KINDS } from "./lib/marks";

function readBackend(relative: string): string {
  return readFileSync(fileURLToPath(new URL(relative, import.meta.url)), "utf8");
}

const SERVICE = readBackend("../../../../backend/app/modules/timeline/service.py");
const SCHEMAS = readBackend("../../../../backend/app/modules/timeline/schemas.py");

describe("window limit", () => {
  it("matches the API's MAX_WINDOW_DAYS", () => {
    const m = /^MAX_WINDOW_DAYS = (\d+)$/m.exec(SERVICE);
    expect(m, "MAX_WINDOW_DAYS not found in service.py").toBeTruthy();
    expect(Number(m![1])).toBe(MAX_WINDOW_DAYS);
  });
});

describe("event kinds", () => {
  it("matches the API's ALL_KINDS, in the same set", () => {
    const block = /ALL_KINDS: tuple\[str, \.\.\.\] = \(([\s\S]*?)\)/.exec(SCHEMAS);
    expect(block, "ALL_KINDS not found in schemas.py").toBeTruthy();
    const backendKinds = [...block![1].matchAll(/"([a-z_]+)"/g)].map((x) => x[1]);
    expect([...backendKinds].sort()).toEqual([...TIMELINE_EVENT_KINDS].sort());
  });

  it("assigns every kind either a map mark or a block highlight", () => {
    // A kind in neither list is a datapoint the API sends and the map
    // silently ignores — it would appear in the rail and nowhere else,
    // which reads as a rendering bug rather than as a deliberate choice.
    const covered = new Set([...MARK_KINDS, ...BLOCK_HIGHLIGHT_KINDS]);
    expect([...TIMELINE_EVENT_KINDS].filter((k) => !covered.has(k))).toEqual([]);
  });

  it("never puts one kind in both lists", () => {
    const both = MARK_KINDS.filter((k) => BLOCK_HIGHLIGHT_KINDS.includes(k));
    expect(both).toEqual([]);
  });
});

describe("copy", () => {
  const LOCALES: [string, Record<string, unknown>][] = [
    ["en", en],
    ["ar", ar],
  ];

  it.each(LOCALES)("%s has a label for every event kind", (_lang, bundle) => {
    // i18next resolves a missing key to the key itself, so a rendered-text
    // assertion would pass on a typo. Read the bundle directly.
    const kinds = (bundle.kind ?? {}) as Record<string, unknown>;
    const missing = TIMELINE_EVENT_KINDS.filter((k) => typeof kinds[k] !== "string");
    expect(missing).toEqual([]);
  });

  it("has the same key set in both locales", () => {
    // Orphaned copy is the failure that rots quietly: a key renamed in one
    // bundle leaves a string nobody renders and nobody deletes.
    const paths = (node: unknown, prefix = ""): string[] => {
      if (node === null || typeof node !== "object") return [prefix];
      return Object.entries(node as Record<string, unknown>).flatMap(([k, v]) =>
        paths(v, prefix ? `${prefix}.${k}` : k),
      );
    };
    // Plural suffixes are deliberately per-language: English has two forms,
    // Arabic six. Compare the base keys, not the variants.
    const base = (p: string): string => p.replace(/_(zero|one|two|few|many|other)$/, "");
    const enKeys = new Set(paths(en).map(base));
    const arKeys = new Set(paths(ar).map(base));
    expect([...enKeys].filter((k) => !arKeys.has(k))).toEqual([]);
    expect([...arKeys].filter((k) => !enKeys.has(k))).toEqual([]);
  });
});

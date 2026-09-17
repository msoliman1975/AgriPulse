// Copy parity for the estate dry run screens.
//
// Same reason as `betaI18n.test.ts`: i18next resolves a missing key to the
// key itself, so a rendered-text assertion passes on a typo. These read the
// bundles directly, and both directions matter — a key that exists in Arabic
// and not English is the one that rots quietly.

import { describe, expect, it } from "vitest";

import ar from "@/i18n/locales/ar/decisionTreesEstate.json";
import en from "@/i18n/locales/en/decisionTreesEstate.json";

function flatten(value: unknown, prefix = ""): string[] {
  if (typeof value === "string") return [prefix];
  if (!value || typeof value !== "object") return [];
  return Object.entries(value as Record<string, unknown>).flatMap(([key, child]) =>
    flatten(child, prefix ? `${prefix}.${key}` : key),
  );
}

describe("decisionTreesEstate copy", () => {
  it("carries the same keys in both languages", () => {
    expect(flatten(en).sort()).toEqual(flatten(ar).sort());
  });

  it("has no empty string", () => {
    for (const [name, bundle] of [
      ["en", en],
      ["ar", ar],
    ] as const) {
      const empties = flatten(bundle).filter((path) => {
        const value = path
          .split(".")
          .reduce<unknown>(
            (node, part) => (node as Record<string, unknown> | undefined)?.[part],
            bundle,
          );
        return typeof value === "string" && value.trim() === "";
      });
      expect(empties, `${name} has empty strings`).toEqual([]);
    }
  });

  it("keeps every interpolation placeholder in both languages", () => {
    // A placeholder dropped in translation renders as nothing: the Arabic
    // sentence then says "cells errored" with no number in it.
    const placeholders = (text: string): string[] =>
      (text.match(/\{\{\s*\w+\s*\}\}/g) ?? []).map((p) => p.replace(/\s/g, "")).sort();
    const read = (bundle: unknown, path: string): unknown =>
      path
        .split(".")
        .reduce<unknown>(
          (node, part) => (node as Record<string, unknown> | undefined)?.[part],
          bundle,
        );

    for (const path of flatten(en)) {
      const left = read(en, path);
      const right = read(ar, path);
      if (typeof left !== "string" || typeof right !== "string") continue;
      expect(placeholders(right), `${path} lost a placeholder in Arabic`).toEqual(
        placeholders(left),
      );
    }
  });
});

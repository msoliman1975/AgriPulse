// What the frontend believes about the investors API, checked against the
// API's own source, plus Arabic/English key parity for the namespace.
//
// A value the backend adds to a Literal and the frontend does not know reads
// as a raw key on screen ("endedBy.buyback"), with no error anywhere.

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import ar from "@/i18n/locales/ar/investors.json";
import en from "@/i18n/locales/en/investors.json";

const SCHEMAS = readFileSync(
  join(__dirname, "../../../../backend/app/modules/investors/schemas.py"),
  "utf8",
);

function literal(name: string): string[] {
  const m = new RegExp(`^${name} = Literal\\[([^\\]]+)\\]`, "m").exec(SCHEMAS);
  if (!m) throw new Error(`${name} not found in schemas.py`);
  return [...m[1].matchAll(/"([^"]+)"/g)].map((x) => x[1]).sort();
}

function keys(obj: unknown, prefix = ""): string[] {
  if (typeof obj !== "object" || obj === null) return [prefix];
  return Object.entries(obj as Record<string, unknown>).flatMap(([k, v]) =>
    keys(v, prefix ? `${prefix}.${k}` : k),
  );
}

describe("investors i18n", () => {
  it("has the same keys in Arabic and English", () => {
    expect(keys(ar).sort()).toEqual(keys(en).sort());
  });

  it.each([
    ["InvestorStatus", "status"],
    ["HoldingStatus", "holdingStatus"],
    ["AcquiredBy", "acquiredBy"],
    ["EndedBy", "endedBy"],
    ["IdType", "idType"],
    ["InvestorType", "type"],
  ])("labels every value of the backend's %s", (literalName, section) => {
    const labelled = Object.keys(
      (en as unknown as Record<string, Record<string, string>>)[section],
    ).sort();
    expect(labelled).toEqual(literal(literalName));
  });
});

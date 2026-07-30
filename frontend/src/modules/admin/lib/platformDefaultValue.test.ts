import { describe, expect, it } from "vitest";

import {
  constraintHint,
  formatTimestamp,
  formatValue,
  parseAndValidate,
} from "./platformDefaultValue";

describe("formatValue", () => {
  it("renders null as the literal `null`, distinct from an empty string", () => {
    // The old editor rendered both as "", so editing a nullable row
    // silently rewrote null -> "" with no way back.
    expect(formatValue(null)).toBe("null");
    expect(formatValue("")).toBe("");
    expect(formatValue(undefined)).toBe("");
  });

  it("passes strings through and JSON-encodes everything else", () => {
    expect(formatValue("open_meteo")).toBe("open_meteo");
    expect(formatValue(30)).toBe("30");
    expect(formatValue(["a", "b"])).toBe('["a","b"]');
  });
});

describe("parseAndValidate — schema", () => {
  it("round-trips null for a nullable key", () => {
    expect(parseAndValidate("null", "string", null)).toBeNull();
    expect(parseAndValidate("null", "number", { nullable: true })).toBeNull();
  });

  it("does not treat `null` as null for a non-nullable numeric key", () => {
    expect(() => parseAndValidate("null", "number", null)).toThrow(/Expected a number/);
  });

  it("rejects an empty numeric field instead of coercing it to 0", () => {
    expect(() => parseAndValidate("  ", "number", null)).toThrow(/Expected a number/);
  });

  it("parses booleans strictly", () => {
    expect(parseAndValidate("true", "boolean", null)).toBe(true);
    expect(parseAndValidate("false", "boolean", null)).toBe(false);
    expect(() => parseAndValidate("yes", "boolean", null)).toThrow(/true.*false/);
  });

  it("enforces array vs object shape", () => {
    expect(parseAndValidate('["a"]', "array", null)).toEqual(["a"]);
    expect(() => parseAndValidate('{"a":1}', "array", null)).toThrow(/JSON array/);
    expect(() => parseAndValidate('["a"]', "object", null)).toThrow(/JSON object/);
    expect(() => parseAndValidate("nope", "object", null)).toThrow(/valid JSON/);
  });
});

describe("parseAndValidate — constraints", () => {
  const zScore = { minimum: 0.1, maximum: 10.0 };
  const pct = { minimum: 0, maximum: 100, integer_only: true };

  it("accepts values inside the range", () => {
    expect(parseAndValidate("2.5", "number", zScore)).toBe(2.5);
    expect(parseAndValidate("30", "number", pct)).toBe(30);
  });

  it("rejects values outside the range", () => {
    expect(() => parseAndValidate("0", "number", zScore)).toThrow(/≥ 0.1/);
    expect(() => parseAndValidate("25", "number", zScore)).toThrow(/≤ 10/);
    expect(() => parseAndValidate("5000", "number", pct)).toThrow(/≤ 100/);
    expect(() => parseAndValidate("-1", "number", pct)).toThrow(/≥ 0/);
  });

  it("rejects fractional values for integer-only keys", () => {
    expect(() => parseAndValidate("30.5", "number", pct)).toThrow(/whole number/);
  });

  it("enforces the choice list", () => {
    const provider = { choices: ["open_meteo"] };
    expect(parseAndValidate("open_meteo", "string", provider)).toBe("open_meteo");
    expect(() => parseAndValidate("banana", "string", provider)).toThrow(/one of: open_meteo/);
  });
});

describe("constraintHint", () => {
  it("summarises the bound the row enforces", () => {
    expect(constraintHint(null)).toBeNull();
    expect(constraintHint({ minimum: 0, maximum: 100 })).toBe("0–100");
    expect(constraintHint({ minimum: 1 })).toBe("≥ 1");
    expect(constraintHint({ maximum: 10 })).toBe("≤ 10");
    expect(constraintHint({ choices: ["a", "b"] })).toBe("one of: a, b");
  });
});

describe("formatTimestamp", () => {
  it("formats an ISO timestamp for the active locale", () => {
    const out = formatTimestamp("2026-05-08T12:33:41.220381+00:00", "en-US");
    // Not the raw ISO string any more — that was the old rendering.
    expect(out).not.toContain("T12:33:41");
    expect(out).toMatch(/2026/);
  });

  it("falls back to the raw value when it cannot be parsed", () => {
    expect(formatTimestamp("not-a-date", "en-US")).toBe("not-a-date");
  });
});

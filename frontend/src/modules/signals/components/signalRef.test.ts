import { describe, expect, it } from "vitest";

import { buildSignalRef, refToJson, refToYaml, valueKeyForKind, type SignalRef } from "./signalRef";

describe("valueKeyForKind", () => {
  it.each([
    ["numeric", "value_numeric"],
    ["categorical", "value_categorical"],
    ["event", "value_event"],
    ["boolean", "value_boolean"],
  ] as const)("maps %s → %s", (kind, expected) => {
    expect(valueKeyForKind(kind)).toBe(expected);
  });

  it("returns null for geopoint (not predicateable)", () => {
    expect(valueKeyForKind("geopoint")).toBeNull();
  });
});

describe("buildSignalRef", () => {
  it("produces the backend-expected shape", () => {
    expect(buildSignalRef("soil_ph", "value_numeric")).toEqual({
      source: "signals",
      code: "soil_ph",
      key: "value_numeric",
    });
  });
});

describe("refToJson", () => {
  it("emits compact JSON", () => {
    const ref: SignalRef = { source: "signals", code: "soil_ph", key: "value_numeric" };
    expect(refToJson(ref)).toBe('{"source":"signals","code":"soil_ph","key":"value_numeric"}');
  });
});

describe("refToYaml", () => {
  it("emits inline mapping form", () => {
    const ref: SignalRef = { source: "signals", code: "scout_severity", key: "value_categorical" };
    expect(refToYaml(ref)).toBe(
      "{ source: signals, code: scout_severity, key: value_categorical }",
    );
  });
});

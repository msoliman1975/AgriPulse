import { describe, expect, it } from "vitest";

import type { CustomFieldDef, CustomFieldValue } from "@/api/reports";

import {
  customCsvCells,
  customCsvHeaders,
  fieldLabel,
  fieldsParam,
  fieldUnit,
  formatCustomCell,
  formatCustomValue,
  isNumericField,
} from "./customFields";

function def(overrides: Partial<CustomFieldDef> = {}): CustomFieldDef {
  return {
    key: "crop_attribute:brix",
    source: "crop_attribute",
    code: "brix",
    name_en: "Brix",
    name_ar: "بريكس",
    value_type: "decimal",
    unit_en: "°Bx",
    unit_ar: "°بركس",
    decimal_places: 1,
    options: null,
    ...overrides,
  };
}

function value(overrides: Partial<CustomFieldValue> = {}): CustomFieldValue {
  return {
    key: "crop_attribute:brix",
    source: "crop_attribute",
    code: "brix",
    value_numeric: null,
    value_text: null,
    value_boolean: null,
    value_date: null,
    value_options: null,
    observed_at: null,
    ...overrides,
  };
}

describe("fieldLabel / fieldUnit", () => {
  it("uses the Arabic name on an Arabic page", () => {
    expect(fieldLabel(def(), "ar")).toBe("بريكس");
    expect(fieldUnit(def(), "ar")).toBe("°بركس");
  });

  it("falls back to English when there is no Arabic name", () => {
    // Every signal takes this path: that catalog has one `name` column.
    const signal = def({ source: "signal", name_ar: null, unit_ar: null });
    expect(fieldLabel(signal, "ar")).toBe("Brix");
    expect(fieldUnit(signal, "ar")).toBe("°Bx");
  });
});

describe("formatCustomValue", () => {
  it("is empty for a block with no value", () => {
    expect(formatCustomValue(def(), undefined, "en")).toBe("");
  });

  it("rounds to the definition's decimal places", () => {
    expect(formatCustomValue(def(), value({ value_numeric: "14.47" }), "en")).toBe("14.5");
  });

  it("passes a number through when no precision was declared", () => {
    // Rounding a value whose precision nobody declared is a decision this
    // layer has no basis to make.
    const d = def({ decimal_places: null });
    expect(formatCustomValue(d, value({ value_numeric: "14.4700" }), "en")).toBe("14.4700");
  });

  it("renders zero and false rather than treating them as missing", () => {
    expect(formatCustomValue(def(), value({ value_numeric: "0" }), "en")).toBe("0.0");
    const bool = def({ value_type: "boolean", decimal_places: null });
    expect(formatCustomValue(bool, value({ value_boolean: false }), "en")).toBe("✗");
    expect(formatCustomValue(bool, value({ value_boolean: true }), "en")).toBe("✓");
  });

  it("maps a single-select code to its localised option label", () => {
    const d = def({
      value_type: "single_select",
      decimal_places: null,
      options: [{ code: "drip", name_en: "Drip", name_ar: "تنقيط" }],
    });
    expect(formatCustomValue(d, value({ value_text: "drip" }), "en")).toBe("Drip");
    expect(formatCustomValue(d, value({ value_text: "drip" }), "ar")).toBe("تنقيط");
  });

  it("shows a stored code whose option was since removed", () => {
    // The reading happened. A blank cell would read as "nothing was entered".
    const d = def({ value_type: "single_select", decimal_places: null, options: [] });
    expect(formatCustomValue(d, value({ value_text: "retired" }), "en")).toBe("retired");
  });

  it("joins a multi-select", () => {
    const d = def({
      value_type: "multi_select",
      decimal_places: null,
      options: [
        { code: "a", name_en: "Alpha", name_ar: null },
        { code: "b", name_en: "Beta", name_ar: null },
      ],
    });
    expect(formatCustomValue(d, value({ value_options: ["a", "b"] }), "en")).toBe("Alpha, Beta");
  });
});

describe("formatCustomCell", () => {
  it("appends the unit to a value", () => {
    expect(
      formatCustomCell(def(), { "crop_attribute:brix": value({ value_numeric: "14" }) }, "en"),
    ).toBe("14.0 °Bx");
  });

  it("never renders a bare unit for a missing value", () => {
    expect(formatCustomCell(def(), {}, "en")).toBe("");
  });
});

describe("isNumericField", () => {
  it("covers both catalogs' numeric type names", () => {
    expect(isNumericField(def({ value_type: "decimal" }))).toBe(true);
    expect(isNumericField(def({ value_type: "integer" }))).toBe(true);
    expect(isNumericField(def({ value_type: "numeric" }))).toBe(true);
    expect(isNumericField(def({ value_type: "text" }))).toBe(false);
    expect(isNumericField(def({ value_type: "categorical" }))).toBe(false);
  });
});

describe("fieldsParam", () => {
  it("is undefined when nothing is picked", () => {
    expect(fieldsParam([])).toBeUndefined();
  });

  it("joins picked keys in order", () => {
    expect(fieldsParam(["signal:a", "crop_attribute:b"])).toBe("signal:a,crop_attribute:b");
  });
});

describe("csv export", () => {
  it("puts the unit in the header, not in every cell", () => {
    // A CSV column of "14.5 °Bx" is text, and text does not sum.
    expect(customCsvHeaders([def()], "en")).toEqual(["Brix (°Bx)"]);
    expect(
      customCsvCells([def()], { "crop_attribute:brix": value({ value_numeric: "14" }) }, "en"),
    ).toEqual(["14.0"]);
  });

  it("emits an empty cell, not a dash, for a missing value", () => {
    expect(customCsvCells([def()], {}, "en")).toEqual([""]);
  });

  it("keeps headers and cells aligned across several columns", () => {
    const brix = def();
    const trap = def({
      key: "signal:trap",
      source: "signal",
      code: "trap",
      name_en: "Trap count",
      name_ar: null,
      value_type: "numeric",
      unit_en: null,
      unit_ar: null,
      decimal_places: null,
    });
    expect(customCsvHeaders([brix, trap], "en")).toHaveLength(2);
    expect(
      customCsvCells(
        [brix, trap],
        { "signal:trap": value({ key: "signal:trap", value_numeric: "3" }) },
        "en",
      ),
    ).toEqual(["", "3"]);
  });
});

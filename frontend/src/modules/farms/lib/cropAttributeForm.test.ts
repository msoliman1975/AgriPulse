import { describe, expect, it } from "vitest";

import type { CropAttributeDefinition } from "@/api/crops";

import {
  buildPayload,
  clearedByGate,
  gateMatches,
  groupDefinitions,
  isRequired,
  isVisible,
  label,
  missingRequired,
  visibleDefinitions,
} from "./cropAttributeForm";

/** These rules mirror `backend/app/modules/farms/crop_attributes.py`. The
 *  server re-validates every save, so a disagreement here does not corrupt
 *  data — it shows the user a form the server then rejects, or hides a field
 *  the server requires. Both are silent until someone tries to save. */

function def(over: Partial<CropAttributeDefinition> & { code: string }): CropAttributeDefinition {
  return {
    id: `id-${over.code}`,
    crop_id: "crop",
    crop_variety_id: null,
    crop_variety_strain_id: null,
    path: "mango",
    name_en: over.code,
    name_ar: `ع-${over.code}`,
    description_en: null,
    description_ar: null,
    value_type: "text",
    unit_en: null,
    unit_ar: null,
    value_min: null,
    value_max: null,
    decimal_places: null,
    text_max_length: null,
    options: null,
    is_required: false,
    required_when: null,
    show_when: null,
    group_code: "establishment",
    group_name_en: "Establishment",
    group_name_ar: "التأسيس",
    sort_order: 1,
    is_reportable: true,
    is_active: true,
    ...over,
  };
}

const GATE = { code: "establishment_method", in: ["grafted_tree", "transplanted_tree"] };

const METHOD = def({
  code: "establishment_method",
  value_type: "single_select",
  is_required: true,
  sort_order: 1,
  options: [
    { code: "seed", name_en: "Seed", name_ar: "بذرة", sort_order: 1 },
    { code: "grafted_tree", name_en: "Grafted tree", name_ar: "شجرة مطعمة", sort_order: 2 },
  ],
});
const TRANSPLANT_DATE = def({
  code: "transplant_date",
  value_type: "date",
  sort_order: 2,
  show_when: GATE,
  required_when: GATE,
});
const NURSERY = def({ code: "nursery_source", sort_order: 3 });

const DEFS = [METHOD, TRANSPLANT_DATE, NURSERY];

// ---- gates ----------------------------------------------------------------

describe("gateMatches", () => {
  it("matches an `in` list and an `eq` scalar", () => {
    expect(gateMatches(GATE, { establishment_method: "grafted_tree" })).toBe(true);
    expect(gateMatches(GATE, { establishment_method: "seed" })).toBe(false);
    expect(gateMatches({ code: "b", eq: true }, { b: true })).toBe(true);
    expect(gateMatches({ code: "b", eq: true }, { b: false })).toBe(false);
  });

  it("fails closed on an unanswered target", () => {
    // An unset establishment method must not reveal the transplant fields, or
    // a half-filled form looks complete.
    expect(gateMatches(GATE, {})).toBe(false);
    expect(gateMatches(GATE, { establishment_method: "" })).toBe(false);
    expect(gateMatches(GATE, { establishment_method: null })).toBe(false);
    expect(gateMatches(null, { establishment_method: "grafted_tree" })).toBe(false);
  });

  it("matches any member of a multi-select target", () => {
    expect(gateMatches({ code: "t", in: ["insecticide"] }, { t: ["fungicide_dust"] })).toBe(false);
    expect(
      gateMatches({ code: "t", in: ["insecticide"] }, { t: ["fungicide_dust", "insecticide"] }),
    ).toBe(true);
  });
});

describe("visibility and requiredness defaults", () => {
  it("absent show_when means always visible, absent required_when means optional", () => {
    // Collapsing these two opposite defaults makes every ungated field
    // mandatory — the exact bug this asserts against.
    expect(isVisible(NURSERY, {})).toBe(true);
    expect(isRequired(NURSERY, {})).toBe(false);
  });

  it("opens visibility and requiredness together with the gate", () => {
    expect(isVisible(TRANSPLANT_DATE, { establishment_method: "seed" })).toBe(false);
    expect(isRequired(TRANSPLANT_DATE, { establishment_method: "seed" })).toBe(false);
    expect(isVisible(TRANSPLANT_DATE, { establishment_method: "grafted_tree" })).toBe(true);
    expect(isRequired(TRANSPLANT_DATE, { establishment_method: "grafted_tree" })).toBe(true);
  });

  it("honours an unconditional is_required", () => {
    expect(isRequired(METHOD, {})).toBe(true);
  });
});

describe("visibleDefinitions", () => {
  it("hides gated fields until their gate opens", () => {
    expect(visibleDefinitions(DEFS, {}).map((d) => d.code)).toEqual([
      "establishment_method",
      "nursery_source",
    ]);
    expect(
      visibleDefinitions(DEFS, { establishment_method: "grafted_tree" }).map((d) => d.code),
    ).toEqual(["establishment_method", "transplant_date", "nursery_source"]);
  });
});

// ---- save blockers --------------------------------------------------------

describe("missingRequired", () => {
  it("reports only visible, required, empty fields", () => {
    expect(missingRequired(DEFS, {})).toEqual(["establishment_method"]);
    expect(missingRequired(DEFS, { establishment_method: "grafted_tree" })).toEqual([
      "transplant_date",
    ]);
    expect(
      missingRequired(DEFS, {
        establishment_method: "grafted_tree",
        transplant_date: "2023-02-18",
      }),
    ).toEqual([]);
  });

  it("treats an empty multi-select as empty", () => {
    const multi = def({ code: "treatment", value_type: "multi_select", is_required: true });
    expect(missingRequired([multi], { treatment: [] })).toEqual(["treatment"]);
    expect(missingRequired([multi], { treatment: ["insecticide"] })).toEqual([]);
  });
});

describe("clearedByGate", () => {
  it("warns about values a closing gate will discard", () => {
    // Switching back to Seed drops the transplant date. The server records
    // `cleared_by_gate`; the user should not have to discover it afterwards.
    expect(
      clearedByGate(DEFS, { establishment_method: "seed", transplant_date: "2023-02-18" }),
    ).toEqual(["transplant_date"]);
  });

  it("stays quiet when the hidden field holds nothing", () => {
    expect(clearedByGate(DEFS, { establishment_method: "seed" })).toEqual([]);
  });
});

// ---- payload --------------------------------------------------------------

describe("buildPayload", () => {
  it("sends every visible field, nulling the blanks", () => {
    expect(
      buildPayload(DEFS, {
        establishment_method: "grafted_tree",
        transplant_date: "2023-02-18",
      }),
    ).toEqual({
      establishment_method: "grafted_tree",
      transplant_date: "2023-02-18",
      nursery_source: null,
    });
  });

  it("explicitly nulls a value whose gate has closed", () => {
    expect(
      buildPayload(DEFS, { establishment_method: "seed", transplant_date: "2023-02-18" }),
    ).toEqual({
      establishment_method: "seed",
      transplant_date: null,
      nursery_source: null,
    });
  });

  it("omits an untouched hidden field so no no-op history row is written", () => {
    expect(buildPayload(DEFS, { establishment_method: "seed" })).toEqual({
      establishment_method: "seed",
      nursery_source: null,
    });
  });
});

// ---- presentation ---------------------------------------------------------

describe("groupDefinitions", () => {
  it("groups in first-seen order and keeps server order within a group", () => {
    const other = def({ code: "z", group_code: "nursery", group_name_en: "Nursery" });
    const groups = groupDefinitions([...DEFS, other]);
    expect(groups.map((g) => g.code)).toEqual(["establishment", "nursery"]);
    expect(groups[0].defs.map((d) => d.code)).toEqual([
      "establishment_method",
      "transplant_date",
      "nursery_source",
    ]);
  });
});

describe("label", () => {
  it("picks Arabic under an ar locale and English otherwise", () => {
    expect(label(METHOD, "en")).toBe("establishment_method");
    expect(label(METHOD, "ar")).toBe("ع-establishment_method");
    expect(label(METHOD, "ar-EG")).toBe("ع-establishment_method");
    // A missing Arabic name falls back rather than rendering blank.
    expect(label({ name_en: "Only EN", name_ar: null }, "ar")).toBe("Only EN");
  });
});

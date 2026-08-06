import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it } from "vitest";

import type { CropAttributeDefinition } from "@/api/crops";
import { setupTestI18n } from "@/i18n/testing";

import {
  CropAttributeEditor,
  draftErrors,
  emptyDraft,
  type EditorDraft,
} from "./CropAttributeEditor";

/** Identity translator — assertions read the key, not a localised string. */
const t = (key: string): string => key;

function draft(over: Partial<EditorDraft> = {}): EditorDraft {
  return { ...emptyDraft(), code: "ok_code", name_en: "N", name_ar: "ن", ...over };
}

function def(over: Partial<CropAttributeDefinition>): CropAttributeDefinition {
  return {
    id: "d",
    crop_id: "c",
    crop_variety_id: null,
    crop_variety_strain_id: null,
    path: "mango",
    code: "c",
    name_en: "C",
    name_ar: "ج",
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
    group_code: null,
    group_name_en: null,
    group_name_ar: null,
    sort_order: 0,
    is_reportable: true,
    is_active: true,
    ...over,
  };
}

describe("draftErrors", () => {
  it("accepts a well-formed draft", () => {
    expect(draftErrors(draft(), t)).toEqual({});
  });

  it("rejects a code that shadows a built-in field", () => {
    // RESERVED_ATTRIBUTE_CODES on the server. An attribute claiming one of
    // these puts two identically-labelled entries in the decision-tree
    // condition builder, one of which is always empty, with nothing to flag
    // it. The server refuses these; catching it here saves a failed save.
    for (const code of ["growth_stage", "planting_date", "soil_texture", "crop_path"]) {
      expect(draftErrors(draft({ code }), t).code).toBe("cropAttrs.err.reserved");
    }
  });

  it("rejects a malformed code", () => {
    expect(draftErrors(draft({ code: "_leading" }), t).code).toBe("cropAttrs.err.code");
    expect(draftErrors(draft({ code: "has space" }), t).code).toBe("cropAttrs.err.code");
    expect(draftErrors(draft({ code: "a".repeat(33) }), t).code).toBe("cropAttrs.err.code");
  });

  it("demands an Arabic name, not just an English one", () => {
    // An EN-only label renders as English inside an otherwise-Arabic form —
    // the exact failure the paired name_en/name_ar columns exist to prevent.
    expect(draftErrors(draft({ name_ar: "" }), t).name_ar).toBe("cropAttrs.err.required");
  });

  it("demands options on a select, and bilingual names for each", () => {
    expect(draftErrors(draft({ value_type: "single_select", options: [] }), t).options).toBe(
      "cropAttrs.err.needOptions",
    );
    expect(
      draftErrors(
        draft({
          value_type: "single_select",
          options: [{ code: "a", name_en: "A", name_ar: "", sort_order: 0 }],
        }),
        t,
      ).options,
    ).toBe("cropAttrs.err.optionNames");
    expect(
      draftErrors(
        draft({
          value_type: "multi_select",
          options: [{ code: "bad code", name_en: "A", name_ar: "أ", sort_order: 0 }],
        }),
        t,
      ).options,
    ).toBe("cropAttrs.err.optionCode");
  });

  it("rejects an inverted numeric range", () => {
    expect(
      draftErrors(draft({ value_type: "integer", value_min: "10", value_max: "5" }), t).value_min,
    ).toBe("cropAttrs.err.range");
  });
});

describe("CropAttributeEditor gate targets", () => {
  beforeEach(async () => {
    await setupTestI18n();
  });

  function renderEditor(siblings: CropAttributeDefinition[]): void {
    const node: ReactNode = (
      <CropAttributeEditor
        draft={draft()}
        onChange={() => {}}
        isEdit={false}
        siblings={siblings}
        varieties={[]}
        strains={[]}
        onVarietyChange={() => {}}
        saving={false}
        error={null}
        onSubmit={() => {}}
        onCancel={() => {}}
      />
    );
    render(node);
  }

  it("only offers single-choice and yes/no fields as gate targets", () => {
    // GATEABLE_VALUE_TYPES on the server. A gate on free text or a number is
    // an equality test no author can reason about from the form, so the
    // server refuses it — offering it here would just produce a 422.
    renderEditor([
      def({ id: "1", code: "method", name_en: "Method", value_type: "single_select" }),
      def({ id: "2", code: "grafted", name_en: "Grafted", value_type: "boolean" }),
      def({ id: "3", code: "notes_txt", name_en: "Notes", value_type: "text" }),
      def({ id: "4", code: "height", name_en: "Height", value_type: "decimal" }),
    ]);

    expect(screen.getAllByRole("option", { name: /Method/ }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("option", { name: /Grafted/ }).length).toBeGreaterThan(0);
    expect(screen.queryByRole("option", { name: /Notes/ })).toBeNull();
    expect(screen.queryByRole("option", { name: /Height/ })).toBeNull();
  });

  it("says so plainly when nothing can be gated on", () => {
    renderEditor([def({ id: "3", code: "notes_txt", name_en: "Notes", value_type: "text" })]);
    expect(screen.getAllByText(/gate on|noGateTargets/i).length).toBeGreaterThan(0);
  });
});

// Guards the wiring the page relies on: the editor must not offer `code` or
// the taxonomy attachment for editing, because both are immutable server-side
// and the PATCH schema forbids extra keys.
describe("CropAttributeEditor immutability", () => {
  beforeEach(async () => {
    await setupTestI18n();
  });

  it("locks code and hides the attachment selectors when editing", () => {
    render(
      <CropAttributeEditor
        draft={draft()}
        onChange={() => {}}
        isEdit
        siblings={[]}
        varieties={[]}
        strains={[]}
        onVarietyChange={() => {}}
        saving={false}
        error={null}
        onSubmit={() => {}}
        onCancel={() => {}}
      />,
    );
    expect(screen.getByLabelText("Code")).toBeDisabled();
    expect(screen.queryByLabelText("Variety")).toBeNull();
  });
});

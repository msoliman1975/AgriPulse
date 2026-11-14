// D20: a template activity picks an input from the catalogue; an input with
// one recommended dose fills the dose and, when empty, the product name.

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import type { Input } from "@/api/inputs";
import { setupTestI18n } from "@/i18n/testing";

import { ActivityInputFields, type ActivityRow } from "./ActivityInputFields";

const SULPHUR = {
  id: "i1",
  scope: "platform",
  code: "sulphur",
  name_en: "Sulphur",
  name_ar: "الكبريت",
  category: "mineral_or_botanical_treatment",
  methods: ["dust"],
  organic_status: "unverified",
  doses: [
    {
      crop_path: "date_palm.medjool",
      value: null,
      value_min: "100",
      value_max: "150",
      unit: "g/plant",
      unit_note: null,
      context: null,
      reference: null,
    },
  ],
} as unknown as Input;

const ROW = {
  key: "k1",
  activity_type: "spraying",
  anchor: "start",
  offset_days: 0,
  duration_days: 1,
  sort_order: 0,
} as unknown as ActivityRow;

beforeEach(async () => {
  await setupTestI18n("en");
});

describe("ActivityInputFields", () => {
  it("fills the dose and product name from an input with one dose", () => {
    const onChange = vi.fn();
    render(<ActivityInputFields row={ROW} inputs={[SULPHUR]} onChange={onChange} />);
    fireEvent.change(screen.getByLabelText("Input"), { target: { value: "i1" } });
    expect(onChange).toHaveBeenCalledWith({
      input_id: "i1",
      product_name: "Sulphur",
      dose_value: 100,
      dose_value_max: 150,
      dose_unit: "g/plant",
    });
  });

  it("keeps a product name and dose the author already typed", () => {
    const onChange = vi.fn();
    render(
      <ActivityInputFields
        row={{ ...ROW, product_name: "Our sulphur", dose_value: 120, dose_unit: "g/plant" }}
        inputs={[SULPHUR]}
        onChange={onChange}
      />,
    );
    fireEvent.change(screen.getByLabelText("Input"), { target: { value: "i1" } });
    expect(onChange).toHaveBeenCalledWith({ input_id: "i1", product_name: "Our sulphur" });
  });
});

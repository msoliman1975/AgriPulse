// The picker shows a saved path: an editor that opens "mango.keitt" sees
// Mango and Keitt selected, without the picker emitting a change.
/* eslint-disable @typescript-eslint/require-await */
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";
import { CropPathFilter } from "./CropPathFilter";

vi.mock("@/api/cropCatalog", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  listAdminCrops: vi.fn(async () => [
    {
      id: "c-potato",
      code: "potato",
      name_en: "Potato",
      name_ar: null,
      classification_depth: "crop_only",
    },
    {
      id: "c-mango",
      code: "mango",
      name_en: "Mango",
      name_ar: null,
      classification_depth: "variety",
    },
  ]),
  listAdminVarieties: vi.fn(async () => [
    {
      id: "v-alph",
      crop_id: "c-mango",
      code: "alphonso",
      name_en: "Alphonso",
      name_ar: null,
      path: "mango.alphonso",
      is_active: true,
    },
    {
      id: "v-keitt",
      crop_id: "c-mango",
      code: "keitt",
      name_en: "Keitt",
      name_ar: null,
      path: "mango.keitt",
      is_active: true,
    },
  ]),
  listAdminStrains: vi.fn(async () => []),
}));

describe("CropPathFilter", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
  });

  it("selects the crop and variety of an initial path without emitting", async () => {
    const onChange = vi.fn();
    render(<CropPathFilter value="mango.keitt" onChange={onChange} scope="platform" />);
    const crop = screen.getByRole<HTMLSelectElement>("combobox", { name: "Crop" });
    await waitFor(() => expect(crop.value).toBe("c-mango"));
    const variety = await screen.findByRole<HTMLSelectElement>("combobox", { name: "Variety" });
    await waitFor(() => expect(variety.value).toBe("v-keitt"));
    expect(onChange).not.toHaveBeenCalled();
  });

  it("leaves everything unselected without a value", async () => {
    render(<CropPathFilter value={null} onChange={vi.fn()} scope="platform" />);
    const crop = screen.getByRole<HTMLSelectElement>("combobox", { name: "Crop" });
    await screen.findByRole("option", { name: "Mango" });
    expect(crop.value).toBe("");
  });
});

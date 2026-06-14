import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import { setupTestI18n } from "@/i18n/testing";
import { CropPicker } from "./CropPicker";

const listCropsMock = vi.hoisted(() => vi.fn());
const listVarietiesMock = vi.hoisted(() => vi.fn());
const listStrainsMock = vi.hoisted(() => vi.fn());
vi.mock("@/api/crops", () => ({
  listCrops: listCropsMock,
  listCropVarieties: listVarietiesMock,
  listVarietyStrains: listStrainsMock,
}));

const sampleCrops = [
  {
    id: "c1",
    code: "wheat",
    name_en: "Wheat",
    name_ar: "قمح",
    scientific_name: null,
    category: "cereal",
    is_perennial: false,
    default_growing_season_days: 180,
    relevant_indices: ["ndvi"],
    classification_depth: "crop_only",
  },
  {
    id: "c2",
    code: "mango",
    name_en: "Mango",
    name_ar: "مانجو",
    scientific_name: null,
    category: "fruit_tree",
    is_perennial: true,
    default_growing_season_days: null,
    relevant_indices: ["ndvi"],
    classification_depth: "variety_strain",
  },
];

const sampleVarieties = [
  {
    id: "v1",
    crop_id: "c2",
    code: "alphonso",
    name_en: "Alphonso",
    name_ar: null,
    path: "mango.alphonso",
  },
];

const sampleStrains = [
  {
    id: "s1",
    crop_variety_id: "v1",
    code: "short",
    name_en: "Short Alphonso",
    name_ar: null,
    path: "mango.alphonso.short",
  },
];

describe("CropPicker", () => {
  beforeEach(() => {
    listCropsMock.mockReset();
    listVarietiesMock.mockReset();
    listStrainsMock.mockReset();
    listCropsMock.mockResolvedValue(sampleCrops);
    listVarietiesMock.mockResolvedValue(sampleVarieties);
    listStrainsMock.mockResolvedValue(sampleStrains);
  });

  it("renders English crop names when locale is en", async () => {
    await setupTestI18n("en");
    render(
      <CropPicker
        cropId={null}
        cropVarietyId={null}
        cropVarietyStrainId={null}
        onChange={() => undefined}
      />,
    );
    await waitFor(() => expect(screen.getByRole("option", { name: "Wheat" })).toBeInTheDocument());
  });

  it("renders Arabic crop names when locale is ar", async () => {
    await setupTestI18n("ar");
    render(
      <CropPicker
        cropId={null}
        cropVarietyId={null}
        cropVarietyStrainId={null}
        onChange={() => undefined}
      />,
    );
    await waitFor(() => expect(screen.getByRole("option", { name: "قمح" })).toBeInTheDocument());
  });

  it("hides variety + strain selects for a crop_only crop", async () => {
    await setupTestI18n("en");
    render(
      <CropPicker
        cropId="c1"
        cropVarietyId={null}
        cropVarietyStrainId={null}
        onChange={() => undefined}
      />,
    );
    await waitFor(() => expect(screen.getByRole("option", { name: "Wheat" })).toBeInTheDocument());
    expect(screen.queryByLabelText("Variety")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Strain")).not.toBeInTheDocument();
  });

  it("shows the strain select for a variety_strain crop", async () => {
    await setupTestI18n("en");
    render(
      <CropPicker
        cropId="c2"
        cropVarietyId="v1"
        cropVarietyStrainId={null}
        onChange={() => undefined}
      />,
    );
    await waitFor(() =>
      expect(screen.getByRole("option", { name: "Short Alphonso" })).toBeInTheDocument(),
    );
    expect(screen.getByLabelText("Variety")).toBeInTheDocument();
    expect(screen.getByLabelText("Strain")).toBeInTheDocument();
  });

  it("reports completeness via onValidityChange for variety_strain depth", async () => {
    await setupTestI18n("en");
    const onValidity = vi.fn();
    const { rerender } = render(
      <CropPicker
        cropId="c2"
        cropVarietyId="v1"
        cropVarietyStrainId={null}
        onChange={() => undefined}
        onValidityChange={onValidity}
      />,
    );
    await waitFor(() => expect(onValidity).toHaveBeenCalledWith(false));
    rerender(
      <CropPicker
        cropId="c2"
        cropVarietyId="v1"
        cropVarietyStrainId="s1"
        onChange={() => undefined}
        onValidityChange={onValidity}
      />,
    );
    await waitFor(() => expect(onValidity).toHaveBeenLastCalledWith(true));
  });
});

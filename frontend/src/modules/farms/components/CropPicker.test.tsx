import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import { setupTestI18n } from "@/i18n/testing";
import { CropPicker } from "./CropPicker";

const listCropsMock = vi.hoisted(() => vi.fn());
const listVarietiesMock = vi.hoisted(() => vi.fn());
vi.mock("@/api/crops", () => ({
  listCrops: listCropsMock,
  listCropVarieties: listVarietiesMock,
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
  },
];

describe("CropPicker", () => {
  beforeEach(() => {
    listCropsMock.mockReset();
    listVarietiesMock.mockReset();
    listCropsMock.mockResolvedValue(sampleCrops);
    listVarietiesMock.mockResolvedValue([]);
  });

  it("renders English crop names when locale is en", async () => {
    await setupTestI18n("en");
    render(<CropPicker cropId={null} cropVarietyId={null} onChange={() => undefined} />);
    await waitFor(() => expect(screen.getByRole("option", { name: "Wheat" })).toBeInTheDocument());
  });

  it("renders Arabic crop names when locale is ar", async () => {
    await setupTestI18n("ar");
    render(<CropPicker cropId={null} cropVarietyId={null} onChange={() => undefined} />);
    await waitFor(() => expect(screen.getByRole("option", { name: "قمح" })).toBeInTheDocument());
  });
});

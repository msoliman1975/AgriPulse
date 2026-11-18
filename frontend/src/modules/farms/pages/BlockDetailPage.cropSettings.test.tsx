// A decision tree's Readiness tab links here (#crop-settings) for a missing
// growth stage, crop attribute or heat-unit start. Those were editable only in
// the console's crop panel, so the link landed on a page that could not set
// them. The page now carries the same controls for the current crop.

import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";

import { setupTestI18n } from "@/i18n/testing";
import { renderAtRoute } from "../test-utils";
import { BlockDetailPage } from "./BlockDetailPage";

const FARM_ID = "11111111-1111-1111-1111-111111111111";
const BLOCK_ID = "22222222-2222-2222-2222-222222222222";

vi.mock("react-oidc-context", () => ({
  useAuth: () => ({ user: { access_token: null } }),
}));
vi.mock("@/modules/farms/components/MapPreview", () => ({ MapPreview: () => null }));
vi.mock("@/modules/imagery/components/ImageryPanel", () => ({ ImageryPanel: () => null }));
vi.mock("@/modules/imagery/components/SubscriptionsTab", () => ({ SubscriptionsTab: () => null }));
vi.mock("@/modules/indices/components/IndexTrendChart", () => ({ IndexTrendChart: () => null }));
// The three crop-settings controls have their own tests; stubs say they are
// mounted for the current assignment.
vi.mock("@/modules/farms/components/GrowthStageControl", () => ({
  GrowthStageControl: ({ assignment }: { assignment: { id: string } }) => (
    <p>growth stage for {assignment.id}</p>
  ),
}));
vi.mock("@/modules/farms/components/HeatUnitStartControl", () => ({
  HeatUnitStartControl: () => <p>heat unit start</p>,
}));
vi.mock("@/modules/farms/components/CropAttributesCard", () => ({
  CropAttributesCard: ({ blockCropId }: { blockCropId: string }) => (
    <p>crop fields for {blockCropId}</p>
  ),
}));
vi.mock("@/api/crops", () => ({
  listCrops: vi.fn().mockResolvedValue([]),
  listCropVarieties: vi.fn().mockResolvedValue([]),
  listVarietyStrains: vi.fn().mockResolvedValue([]),
}));
vi.mock("@/api/attachments", () => ({
  listFarmAttachments: vi.fn().mockResolvedValue([]),
  listBlockAttachments: vi.fn().mockResolvedValue([]),
  initFarmAttachment: vi.fn(),
  finalizeFarmAttachment: vi.fn(),
  deleteFarmAttachment: vi.fn(),
  initBlockAttachment: vi.fn(),
  finalizeBlockAttachment: vi.fn(),
  deleteBlockAttachment: vi.fn(),
}));

const getBlockMock = vi.hoisted(() => vi.fn());
vi.mock("@/api/blocks", () => ({
  getBlock: getBlockMock,
  archiveBlock: vi.fn(),
}));

const listBlockCropsMock = vi.hoisted(() => vi.fn());
vi.mock("@/api/cropAssignments", () => ({
  assignBlockCrop: vi.fn(),
  listBlockCrops: listBlockCropsMock,
}));

const getFarmMock = vi.hoisted(() => vi.fn());
vi.mock("@/api/farms", () => ({
  getFarm: getFarmMock,
}));

describe("BlockDetailPage crop settings", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    getBlockMock.mockReset();
    listBlockCropsMock.mockReset();
    getFarmMock.mockReset();
    getFarmMock.mockResolvedValue({ id: FARM_ID, name: "Test Farm" });
    getBlockMock.mockResolvedValue({
      id: BLOCK_ID,
      farm_id: FARM_ID,
      code: "B-1",
      name: null,
      boundary: { type: "Polygon", coordinates: [] },
      area_m2: 1000,
      irrigation_system: null,
      unit_type: "block",
      tags: [],
      status: "active",
    });
  });

  it("shows growth stage, heat-unit start and crop fields for the current crop", async () => {
    listBlockCropsMock.mockResolvedValue([
      { id: "bc-old", is_current: false, season_label: "2025", crop_path: "date_palm" },
      { id: "bc-now", is_current: true, season_label: "2026", crop_path: "date_palm.medjool" },
    ]);
    renderAtRoute(<BlockDetailPage />, {
      route: `/farms/${FARM_ID}/blocks/${BLOCK_ID}`,
      path: "/farms/:farmId/blocks/:blockId",
    });
    expect(await screen.findByText("growth stage for bc-now")).toBeInTheDocument();
    expect(screen.getByText("heat unit start")).toBeInTheDocument();
    expect(screen.getByText("crop fields for bc-now")).toBeInTheDocument();
    expect(document.getElementById("crop-settings")).not.toBeNull();
  });

  it("shows none of them without a current crop", async () => {
    listBlockCropsMock.mockResolvedValue([]);
    renderAtRoute(<BlockDetailPage />, {
      route: `/farms/${FARM_ID}/blocks/${BLOCK_ID}`,
      path: "/farms/:farmId/blocks/:blockId",
    });
    await waitFor(() => expect(getBlockMock).toHaveBeenCalled());
    await screen.findAllByText(/B-1/);
    expect(screen.queryByText(/growth stage for/)).toBeNull();
  });

  it("offers the way back to Readiness when it was opened from there", async () => {
    listBlockCropsMock.mockResolvedValue([]);
    const back = "/decision-trees-beta/x?tab=readiness";
    renderAtRoute(<BlockDetailPage />, {
      route: `/farms/${FARM_ID}/blocks/${BLOCK_ID}?returnTo=${encodeURIComponent(back)}`,
      path: "/farms/:farmId/blocks/:blockId",
    });
    const link = await screen.findByRole("link", { name: "Back to readiness" });
    expect(link).toHaveAttribute("href", back);
  });
});

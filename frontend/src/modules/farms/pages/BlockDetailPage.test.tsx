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
vi.mock("@/api/crops", () => ({
  listCrops: vi.fn().mockResolvedValue([]),
  listCropVarieties: vi.fn().mockResolvedValue([]),
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

describe("BlockDetailPage", () => {
  beforeEach(() => {
    getBlockMock.mockReset();
    listBlockCropsMock.mockReset();
    getBlockMock.mockResolvedValue({
      id: BLOCK_ID,
      farm_id: FARM_ID,
      code: "B-1",
      name: null,
      boundary: { type: "Polygon", coordinates: [] },
      centroid: { type: "Point", coordinates: [31, 30] },
      area_m2: 1000,
      area_value: 0.24,
      area_unit: "feddan",
      aoi_hash: "deadbeef",
      elevation_m: null,
      irrigation_system: "drip",
      irrigation_source: null,
      soil_texture: null,
      salinity_class: null,
      soil_ph: null,
      responsible_user_id: null,
      notes: null,
      tags: [],
      status: "active",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    });
    listBlockCropsMock.mockResolvedValue([]);
  });

  it("renders block detail in English (LTR)", async () => {
    await setupTestI18n("en");
    renderAtRoute(<BlockDetailPage />, {
      route: `/farms/${FARM_ID}/blocks/${BLOCK_ID}`,
      path: "/farms/:farmId/blocks/:blockId",
    });
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: /Block B-1/ })).toBeInTheDocument(),
    );
    expect(document.documentElement.getAttribute("dir")).toBe("ltr");
  });

  it("renders block detail in Arabic (RTL)", async () => {
    await setupTestI18n("ar");
    renderAtRoute(<BlockDetailPage />, {
      route: `/farms/${FARM_ID}/blocks/${BLOCK_ID}`,
      path: "/farms/:farmId/blocks/:blockId",
    });
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: /القطعة B-1/ })).toBeInTheDocument(),
    );
    expect(document.documentElement.getAttribute("dir")).toBe("rtl");
  });
});

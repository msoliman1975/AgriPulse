import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";

import { setupTestI18n } from "@/i18n/testing";
import { renderAtRoute } from "../test-utils";
import { BlockEditPage } from "./BlockEditPage";

const FARM_ID = "11111111-1111-1111-1111-111111111111";
const BLOCK_ID = "22222222-2222-2222-2222-222222222222";

vi.mock("react-oidc-context", () => ({
  useAuth: () => ({ user: { access_token: null } }),
}));
vi.mock("@/modules/farms/components/MapDraw", () => ({ MapDraw: () => null }));

const getBlockMock = vi.hoisted(() => vi.fn());
vi.mock("@/api/blocks", () => ({
  getBlock: getBlockMock,
  updateBlock: vi.fn(),
}));

describe("BlockEditPage", () => {
  beforeEach(() => {
    getBlockMock.mockReset();
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
      irrigation_system: null,
      irrigation_source: null,
      soil_texture: null,
      salinity_class: null,
      soil_ph: null,
      agronomist_membership_id: null,
      notes: null,
      tags: [],
      status: "active",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    });
  });

  it("renders the heading in English (LTR)", async () => {
    await setupTestI18n("en");
    renderAtRoute(<BlockEditPage />, {
      route: `/farms/${FARM_ID}/blocks/${BLOCK_ID}/edit`,
      path: "/farms/:farmId/blocks/:blockId/edit",
    });
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Edit block" })).toBeInTheDocument(),
    );
    expect(document.documentElement.getAttribute("dir")).toBe("ltr");
  });

  it("pre-fills the planting layout and shows the spacing density (D23)", async () => {
    getBlockMock.mockResolvedValueOnce({
      ...(await getBlockMock.getMockImplementation()?.()),
      row_spacing_m: "10.00",
      in_row_spacing_m: "8.00",
      plant_count: 240,
    });
    await setupTestI18n("en");
    renderAtRoute(<BlockEditPage />, {
      route: `/farms/${FARM_ID}/blocks/${BLOCK_ID}/edit`,
      path: "/farms/:farmId/blocks/:blockId/edit",
    });
    await waitFor(() => expect(screen.getByLabelText("Row spacing (m)")).toHaveValue(10));
    expect(screen.getByLabelText("In-row spacing (m)")).toHaveValue(8);
    expect(screen.getByLabelText("Plant count")).toHaveValue(240);
    // 10,000 m² / (10 m × 8 m), the manual's Medjool layout.
    expect(screen.getByText("125 plants per hectare from this spacing")).toBeInTheDocument();
  });

  it("renders the heading in Arabic (RTL)", async () => {
    await setupTestI18n("ar");
    renderAtRoute(<BlockEditPage />, {
      route: `/farms/${FARM_ID}/blocks/${BLOCK_ID}/edit`,
      path: "/farms/:farmId/blocks/:blockId/edit",
    });
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "تعديل القطعة" })).toBeInTheDocument(),
    );
    expect(document.documentElement.getAttribute("dir")).toBe("rtl");
  });
});

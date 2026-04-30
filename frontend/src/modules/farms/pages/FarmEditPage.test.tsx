import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";

import { setupTestI18n } from "@/i18n/testing";
import { renderAtRoute } from "../test-utils";
import { FarmEditPage } from "./FarmEditPage";

const FARM_ID = "11111111-1111-1111-1111-111111111111";

vi.mock("react-oidc-context", () => ({
  useAuth: () => ({ user: { access_token: null } }),
}));
vi.mock("@/modules/farms/components/MapDraw", () => ({ MapDraw: () => null }));
vi.mock("@/modules/farms/components/MapPreview", () => ({ MapPreview: () => null }));

const getFarmMock = vi.hoisted(() => vi.fn());
vi.mock("@/api/farms", () => ({
  getFarm: getFarmMock,
  updateFarm: vi.fn(),
}));

describe("FarmEditPage", () => {
  beforeEach(() => {
    getFarmMock.mockReset();
    getFarmMock.mockResolvedValue({
      id: FARM_ID,
      code: "FARM-1",
      name: "Existing Farm",
      description: null,
      boundary: { type: "MultiPolygon", coordinates: [] },
      centroid: { type: "Point", coordinates: [31, 30] },
      area_m2: 0,
      area_value: 0,
      area_unit: "feddan",
      elevation_m: null,
      governorate: null,
      district: null,
      nearest_city: null,
      address_line: null,
      farm_type: "commercial",
      ownership_type: null,
      primary_water_source: null,
      established_date: null,
      tags: [],
      status: "active",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    });
  });

  it("renders the heading in English (LTR)", async () => {
    await setupTestI18n("en");
    renderAtRoute(<FarmEditPage />, {
      route: `/farms/${FARM_ID}/edit`,
      path: "/farms/:farmId/edit",
    });
    await waitFor(() => expect(screen.getByLabelText("Name")).toBeInTheDocument());
    expect(screen.getByRole("heading", { name: "Edit" })).toBeInTheDocument();
    expect(document.documentElement.getAttribute("dir")).toBe("ltr");
  });

  it("renders the heading in Arabic (RTL)", async () => {
    await setupTestI18n("ar");
    renderAtRoute(<FarmEditPage />, {
      route: `/farms/${FARM_ID}/edit`,
      path: "/farms/:farmId/edit",
    });
    await waitFor(() => expect(screen.getByLabelText("الاسم")).toBeInTheDocument());
    expect(document.documentElement.getAttribute("dir")).toBe("rtl");
  });
});

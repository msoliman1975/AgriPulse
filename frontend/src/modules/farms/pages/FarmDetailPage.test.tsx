import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";

import { setupTestI18n } from "@/i18n/testing";
import { renderAtRoute } from "../test-utils";
import { FarmDetailPage } from "./FarmDetailPage";

const FARM_ID = "11111111-1111-1111-1111-111111111111";

function makeJwt(payload: object): string {
  return `${btoa(JSON.stringify({ alg: "none" }))}.${btoa(JSON.stringify(payload))}.sig`;
}

vi.mock("react-oidc-context", () => ({
  useAuth: () => ({
    user: { access_token: makeJwt({ tenant_role: "TenantAdmin" }) },
  }),
}));
vi.mock("@/modules/farms/components/MapDraw", () => ({ MapDraw: () => null }));
vi.mock("@/modules/farms/components/MapPreview", () => ({ MapPreview: () => null }));

const getFarmMock = vi.hoisted(() => vi.fn());
const archiveFarmMock = vi.hoisted(() => vi.fn());
vi.mock("@/api/farms", () => ({
  getFarm: getFarmMock,
  archiveFarm: archiveFarmMock,
}));

const listBlocksMock = vi.hoisted(() => vi.fn());
vi.mock("@/api/blocks", () => ({
  listBlocks: listBlocksMock,
}));

describe("FarmDetailPage", () => {
  beforeEach(() => {
    getFarmMock.mockReset();
    listBlocksMock.mockReset();
    getFarmMock.mockResolvedValue({
      id: FARM_ID,
      code: "FARM-1",
      name: "Beheira Farm",
      description: null,
      boundary: {
        type: "MultiPolygon",
        coordinates: [
          [
            [
              [31.2, 30.0],
              [31.21, 30.0],
              [31.21, 30.01],
              [31.2, 30.01],
              [31.2, 30.0],
            ],
          ],
        ],
      },
      centroid: { type: "Point", coordinates: [31.205, 30.005] },
      area_m2: 42008.3,
      area_value: 10,
      area_unit: "feddan",
      elevation_m: null,
      governorate: "Beheira",
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
    listBlocksMock.mockResolvedValue({ items: [], next_cursor: null });
  });

  it("renders the farm header in English (LTR)", async () => {
    await setupTestI18n("en");
    renderAtRoute(<FarmDetailPage />, {
      route: `/farms/${FARM_ID}`,
      path: "/farms/:farmId",
    });
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Beheira Farm" })).toBeInTheDocument(),
    );
    expect(screen.getByText("Blocks")).toBeInTheDocument();
    expect(document.documentElement.getAttribute("dir")).toBe("ltr");
  });

  it("renders in Arabic (RTL)", async () => {
    await setupTestI18n("ar");
    renderAtRoute(<FarmDetailPage />, {
      route: `/farms/${FARM_ID}`,
      path: "/farms/:farmId",
    });
    await waitFor(() => expect(screen.getByText("القطع")).toBeInTheDocument());
    expect(document.documentElement.getAttribute("dir")).toBe("rtl");
  });
});

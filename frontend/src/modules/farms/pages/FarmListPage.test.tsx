import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";

import { setupTestI18n } from "@/i18n/testing";
import { renderAtRoute } from "../test-utils";
import { FarmListPage } from "./FarmListPage";

vi.mock("react-oidc-context", () => ({
  useAuth: () => ({
    user: { access_token: makeJwt({ tenant_role: "TenantAdmin" }) },
  }),
}));

const listFarmsMock = vi.hoisted(() => vi.fn());
vi.mock("@/api/farms", () => ({
  listFarms: listFarmsMock,
}));

function makeJwt(payload: object): string {
  const header = btoa(JSON.stringify({ alg: "none", typ: "JWT" }));
  const body = btoa(JSON.stringify(payload));
  return `${header}.${body}.sig`;
}

describe("FarmListPage", () => {
  beforeEach(() => {
    listFarmsMock.mockReset();
    listFarmsMock.mockResolvedValue({
      items: [
        {
          id: "11111111-1111-1111-1111-111111111111",
          code: "FARM-1",
          name: "Test Farm",
          description: null,
          centroid: { type: "Point", coordinates: [31, 30] },
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
        },
      ],
      next_cursor: null,
    });
  });

  it("renders the heading in English (LTR)", async () => {
    await setupTestI18n("en");
    renderAtRoute(<FarmListPage />, { route: "/farms", path: "/farms" });
    expect(screen.getByRole("heading", { name: "Farms" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Test Farm")).toBeInTheDocument());
    expect(screen.getByText("New farm")).toBeInTheDocument();
    expect(document.documentElement.getAttribute("dir")).toBe("ltr");
  });

  it("renders the heading in Arabic (RTL)", async () => {
    await setupTestI18n("ar");
    renderAtRoute(<FarmListPage />, { route: "/farms", path: "/farms" });
    expect(screen.getByRole("heading", { name: "المزارع" })).toBeInTheDocument();
    expect(document.documentElement.getAttribute("dir")).toBe("rtl");
  });
});

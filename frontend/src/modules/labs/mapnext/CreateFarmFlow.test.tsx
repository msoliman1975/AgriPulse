import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Polygon } from "geojson";

import { setupTestI18n } from "@/i18n/testing";
import { PrefsProvider } from "@/prefs/PrefsContext";

import { CreateFarmFlow } from "./CreateFarmFlow";

vi.mock("react-oidc-context", () => ({
  useAuth: () => ({ user: { access_token: "" } }),
}));

const canCreate = vi.hoisted(() => ({ value: true }));
vi.mock("@/rbac/useCapability", () => ({
  useCapability: () => canCreate.value,
}));

const createFarmMock = vi.hoisted(() => vi.fn());
vi.mock("@/api/farms", async () => {
  const actual = await vi.importActual<object>("@/api/farms");
  return { ...actual, createFarm: createFarmMock, getFarm: vi.fn() };
});

vi.mock("@/api/countries", () => ({
  listCountries: () => Promise.resolve([{ id: "1", code: "EG", name_en: "Egypt", name_ar: "مصر", is_active: true }]),
}));

// A valid ring inside the supported bbox, and one outside it.
// NOTE: a self-intersecting ring is NOT covered here — ensureValidMultiPolygon
// only runs booleanValid (no `kinks`), unlike ensureValidPolygon, so bow-ties
// slip through the shared helper. Pre-existing for every farm-boundary
// surface; worth fixing in lib/geometry.ts separately.
const VALID_RING: Polygon = {
  type: "Polygon",
  coordinates: [[[31.0, 30.0], [31.02, 30.0], [31.02, 30.02], [31.0, 30.02], [31.0, 30.0]]],
};
const OUT_OF_BBOX_RING: Polygon = {
  type: "Polygon",
  coordinates: [[[10.0, 5.0], [10.02, 5.0], [10.02, 5.02], [10.0, 5.02], [10.0, 5.0]]],
};

// MapCanvas needs maplibre (unavailable in jsdom). Stub it and expose the
// draw callback as a button so the flow's capture step can be driven.
const drawn = vi.hoisted(() => ({ polygon: null as Polygon | null }));
vi.mock("../map/MapCanvas", () => ({
  MapCanvas: ({
    onPolygonDrawn,
  }: {
    onPolygonDrawn?: (p: Polygon, areaM2: number, target: string) => void;
  }) => (
    <button type="button" onClick={() => onPolygonDrawn?.(drawn.polygon as Polygon, 40_000, "farm_aoi")}>
      stub-finish-draw
    </button>
  ),
}));

function renderFlow() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <PrefsProvider>
        <MemoryRouter initialEntries={["/labs/map?create=farm"]}>
          <Routes>
            <Route path="/labs/map" element={<CreateFarmFlow />} />
            <Route path="/labs/map/:farmId" element={<p>landed-on-console</p>} />
          </Routes>
        </MemoryRouter>
      </PrefsProvider>
    </QueryClientProvider>,
  );
}

describe("CreateFarmFlow", () => {
  beforeEach(() => {
    createFarmMock.mockReset();
    canCreate.value = true;
    drawn.polygon = VALID_RING;
  });

  it("starts on the boundary step with both capture modes", async () => {
    await setupTestI18n("en");
    renderFlow();

    expect(screen.getByRole("heading", { level: 1, name: /New farm/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Draw boundary/ })).toBeInTheDocument();
    expect(screen.getByText(/Upload file/)).toBeInTheDocument();
    // Details are not asked for until there is a boundary.
    expect(screen.queryByLabelText("Code")).not.toBeInTheDocument();
  });

  it("captures a drawn boundary, then creates the farm and lands on its console", async () => {
    await setupTestI18n("en");
    createFarmMock.mockResolvedValue({ id: "farm-9", code: "SUEZ-02", name: "Suez East", area_m2: 1, area_value: 1 });
    renderFlow();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "stub-finish-draw" }));

    // Step 2 appears once a boundary exists.
    await user.type(await screen.findByLabelText("Code"), "SUEZ-02");
    await user.type(screen.getByLabelText("Name"), "Suez East");
    await user.click(screen.getByRole("button", { name: "Create farm" }));

    await waitFor(() => expect(createFarmMock).toHaveBeenCalledTimes(1));
    const payload = createFarmMock.mock.calls[0][0];
    expect(payload.code).toBe("SUEZ-02");
    expect(payload.name).toBe("Suez East");
    // The drawn Polygon is wrapped into the MultiPolygon the API requires.
    expect(payload.boundary.type).toBe("MultiPolygon");
    expect(payload.boundary.coordinates[0]).toEqual(VALID_RING.coordinates);

    expect(await screen.findByText("landed-on-console")).toBeInTheDocument();
  });

  it("rejects an out-of-bounds boundary without calling the API", async () => {
    await setupTestI18n("en");
    drawn.polygon = OUT_OF_BBOX_RING;
    renderFlow();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "stub-finish-draw" }));
    await user.type(await screen.findByLabelText("Code"), "SUEZ-02");
    await user.type(screen.getByLabelText("Name"), "Suez East");
    await user.click(screen.getByRole("button", { name: "Create farm" }));

    expect(await screen.findByText(/outside/i)).toBeInTheDocument();
    expect(createFarmMock).not.toHaveBeenCalled();
  });

  it("refuses to render for a user without farm.create", async () => {
    await setupTestI18n("en");
    canCreate.value = false;
    renderFlow();

    expect(screen.getByText(/don’t have permission/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Draw boundary/ })).not.toBeInTheDocument();
  });
});

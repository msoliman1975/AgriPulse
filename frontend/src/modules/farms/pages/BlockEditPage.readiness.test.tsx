// The Readiness tab's "Edit block" link for a missing soil texture or
// salinity class: the form must load the block's values, save what is set,
// and land the user back on the Readiness tab they came from.

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";
import { PrefsProvider } from "@/prefs/PrefsContext";

import { BlockEditPage } from "./BlockEditPage";

const FARM = "11111111-1111-1111-1111-111111111111";
const BLOCK = "22222222-2222-2222-2222-222222222222";
const BACK = "/decision-trees-beta/date_palm_medjool_canopy_diagnosis?tab=readiness";

vi.mock("react-oidc-context", () => ({ useAuth: () => ({ user: { access_token: null } }) }));
vi.mock("@/modules/farms/components/MapDraw", () => ({ MapDraw: () => null }));

const h = vi.hoisted(() => ({
  getBlock: vi.fn(),
  updateBlock: vi.fn(),
  preview: vi.fn(),
}));
vi.mock("@/api/blocks", () => ({ getBlock: h.getBlock, updateBlock: h.updateBlock }));
vi.mock("@/api/farmDecisionTrees", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/farmDecisionTrees")>()),
  previewFarmTreeImpact: h.preview,
}));

function Where() {
  const loc = useLocation();
  return <p data-testid="where">{`${loc.pathname}${loc.search}`}</p>;
}

function renderEdit(route: string) {
  return render(
    <PrefsProvider>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path="/farms/:farmId/blocks/:blockId/edit" element={<BlockEditPage />} />
          <Route path="*" element={<Where />} />
        </Routes>
      </MemoryRouter>
    </PrefsProvider>,
  );
}

const block = {
  id: BLOCK,
  farm_id: FARM,
  code: "B-1",
  name: null,
  boundary: {
    type: "Polygon",
    coordinates: [
      [
        [31.0, 30.0],
        [31.001, 30.0],
        [31.001, 30.001],
        [31.0, 30.001],
        [31.0, 30.0],
      ],
    ],
  },
  centroid: { type: "Point", coordinates: [31, 30] },
  area_m2: 1000,
  irrigation_system: null,
  irrigation_source: null,
  soil_texture: null,
  salinity_class: null,
  soil_ph: null,
  agronomist_membership_id: null,
  notes: null,
  tags: [],
  status: "active",
};

describe("BlockEditPage from a Readiness fix link", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    h.getBlock.mockReset();
    h.updateBlock.mockReset();
    h.preview.mockReset();
    h.getBlock.mockResolvedValue(block);
    h.updateBlock.mockResolvedValue(block);
    h.preview.mockResolvedValue({ changes_anything: false, exclusions_cleared: [] });
  });

  it("saves soil texture and salinity, then returns to the Readiness tab", async () => {
    renderEdit(`/farms/${FARM}/blocks/${BLOCK}/edit?returnTo=${encodeURIComponent(BACK)}`);
    const user = userEvent.setup();

    const soil = await screen.findByLabelText("Soil texture");
    await user.selectOptions(soil, "loam");
    await user.selectOptions(screen.getByLabelText("Salinity"), "slightly_saline");
    await user.click(screen.getByRole("button", { name: "Save block" }));

    await waitFor(() => expect(h.updateBlock).toHaveBeenCalledTimes(1));
    expect(h.updateBlock.mock.calls[0][0]).toBe(BLOCK);
    expect(h.updateBlock.mock.calls[0][1]).toMatchObject({
      soil_texture: "loam",
      salinity_class: "slightly_saline",
    });
    expect(await screen.findByTestId("where")).toHaveTextContent(BACK);
  });

  it("shows the values already stored", async () => {
    h.getBlock.mockResolvedValue({ ...block, soil_texture: "clay", salinity_class: "non_saline" });
    renderEdit(`/farms/${FARM}/blocks/${BLOCK}/edit`);
    expect(await screen.findByLabelText("Soil texture")).toHaveValue("clay");
    expect(screen.getByLabelText("Salinity")).toHaveValue("non_saline");
  });

  it("ignores a returnTo that leaves the app", async () => {
    renderEdit(
      `/farms/${FARM}/blocks/${BLOCK}/edit?returnTo=${encodeURIComponent("//evil.example")}`,
    );
    const user = userEvent.setup();
    await screen.findByLabelText("Soil texture");
    await user.click(screen.getByRole("button", { name: "Save block" }));
    expect(await screen.findByTestId("where")).toHaveTextContent(`/farms/${FARM}/blocks/${BLOCK}`);
  });
});

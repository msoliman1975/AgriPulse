import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Crop, CropVariety, CropVarietyStrain, PhenologyStage } from "@/api/crops";
import { setupTestI18n } from "@/i18n/testing";

import { PlatformCatalogPage } from "./PlatformCatalogPage";

/*
 * What these cover is the one rule the whole screen exists to enforce:
 * phenology and size classes resolve deepest-non-NULL-wins and an override
 * replaces its parent wholesale. Get it wrong in either direction and the
 * damage is silent —
 *
 *   * editing in place at an inheriting node rewrites the ladder for every
 *     other node inheriting the same one;
 *   * starting an override from an empty list strips every stage the parent
 *     defines, and nobody finds out until a block fails to advance.
 *
 * Plus the reach the screen was built for: the GDD base temperature, which
 * the admin API has always accepted and no control has ever written.
 */

const MANGO_STAGES: PhenologyStage[] = [
  {
    code: "pre_flowering",
    name_en: "Pre-flowering",
    name_ar: "ما قبل الإزهار",
    order: 1,
    advance: { mode: "calendar_doy", start_doy: "12-01", end_doy: "01-31" },
  },
  {
    code: "flowering",
    name_en: "Flowering",
    name_ar: "إزهار",
    order: 2,
    advance: { mode: "calendar_doy", start_doy: "02-01", end_doy: "03-31" },
  },
];

const MANGO: Crop = {
  id: "crop-mango",
  code: "mango",
  name_en: "Mango",
  name_ar: "مانجو",
  scientific_name: null,
  category: "fruit_tree",
  is_perennial: true,
  default_growing_season_days: null,
  relevant_indices: ["ndvi"],
  classification_depth: "variety_strain",
  is_active: true,
  gdd_base_temp_c: null,
  gdd_upper_temp_c: null,
  phenology_stages: { stages: MANGO_STAGES },
  size_classes: null,
  default_thresholds: null,
};

const WHEAT: Crop = {
  id: "crop-wheat",
  code: "wheat",
  name_en: "Wheat",
  name_ar: "قمح",
  scientific_name: null,
  category: "cereal",
  is_perennial: false,
  default_growing_season_days: null,
  relevant_indices: ["ndvi"],
  classification_depth: "crop_only",
  is_active: true,
  gdd_base_temp_c: null,
  gdd_upper_temp_c: null,
  phenology_stages: null,
  size_classes: null,
  default_thresholds: null,
};

// Alphonso inherits mango's ladder; A1 carries one of its own.
const ALPHONSO: CropVariety = {
  id: "var-alphonso",
  crop_id: MANGO.id,
  code: "alphonso",
  name_en: "Alphonso",
  name_ar: null,
  path: "mango.alphonso",
  is_active: true,
  phenology_stages_override: null,
  size_classes_override: null,
  default_thresholds: null,
};

const A1: CropVarietyStrain = {
  id: "strain-a1",
  crop_variety_id: ALPHONSO.id,
  code: "a1",
  name_en: "Clone A1",
  name_ar: null,
  path: "mango.alphonso.a1",
  is_active: true,
  phenology_stages_override: {
    stages: [
      {
        code: "harvest",
        name_en: "Harvest",
        name_ar: "حصاد",
        order: 1,
        advance: { mode: "calendar_doy", start_doy: "06-01", end_doy: "07-31" },
      },
    ],
  },
  size_classes_override: null,
  default_thresholds: null,
};

const updateCrop = vi.fn(() => Promise.resolve(MANGO));
const updateVariety = vi.fn(() => Promise.resolve(ALPHONSO));
const updateStrain = vi.fn(() => Promise.resolve(A1));

vi.mock("@/api/cropCatalog", async () => {
  const actual = await vi.importActual<typeof import("@/api/cropCatalog")>("@/api/cropCatalog");
  return {
    ...actual,
    listAdminCrops: vi.fn(() => Promise.resolve([MANGO, WHEAT])),
    listAdminVarieties: vi.fn(() => Promise.resolve([ALPHONSO])),
    listAdminStrains: vi.fn(() => Promise.resolve([A1])),
    listAdminCropAttributes: vi.fn(() => Promise.resolve([])),
    updateCrop: (...args: unknown[]) => updateCrop(...(args as [])),
    updateVariety: (...args: unknown[]) => updateVariety(...(args as [])),
    updateStrain: (...args: unknown[]) => updateStrain(...(args as [])),
  };
});

vi.mock("@/rbac/useCapability", () => ({
  useCapability: () => true,
}));

function renderAt(search: string): void {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <MemoryRouter initialEntries={[`/platform/catalog${search}`]}>
      <QueryClientProvider client={qc}>
        <PlatformCatalogPage />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

describe("<PlatformCatalogPage>", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    vi.clearAllMocks();
  });

  // Selection is the URL, so a node can be linked to and restored on reload
  // — including a node two levels down that loads lazily.
  it("restores a deep-linked node and names the level it inherits from", async () => {
    renderAt("?node=mango.alphonso&tab=stages");

    expect(await screen.findByText("Stage ladder inherited from mango.")).toBeInTheDocument();
    // Inherited means not editable in place: the offer is an override.
    expect(screen.getByRole("button", { name: "Create an override" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
  });

  it("starts an override as a copy of the inherited ladder, and writes it to the variety", async () => {
    const user = userEvent.setup();
    renderAt("?node=mango.alphonso&tab=stages");

    await user.click(await screen.findByRole("button", { name: "Create an override" }));

    // Starting empty would silently strip every stage the crop defines.
    const codes = screen.getAllByLabelText<HTMLInputElement>("Code");
    expect(codes.map((i) => i.value)).toEqual(["pre_flowering", "flowering"]);

    await user.click(screen.getByRole("button", { name: "Save calendar" }));

    await waitFor(() => expect(updateVariety).toHaveBeenCalled());
    const [varietyId, patch] = updateVariety.mock.calls[0] as unknown as [
      string,
      { phenology_stages_override?: { stages: PhenologyStage[] } },
    ];
    expect(varietyId).toBe(ALPHONSO.id);
    expect(patch.phenology_stages_override?.stages.map((s) => s.code)).toEqual([
      "pre_flowering",
      "flowering",
    ]);
    // The crop's own ladder must be untouched — that is the whole point.
    expect(updateCrop).not.toHaveBeenCalled();
  });

  // Clearing the column is the supported way back; there is no delete route.
  it("reverts an owned override by sending null", async () => {
    const user = userEvent.setup();
    renderAt("?node=mango.alphonso.a1&tab=stages");

    // A strain sits three chained lazy fetches deep — crops, then that crop's
    // varieties, then that variety's strains. Wait on the inspector heading,
    // which only says "Clone A1" once the strain itself has resolved; the
    // provenance line below it is then safe to assert synchronously.
    await screen.findByRole("heading", { name: "Clone A1" }, { timeout: 5000 });
    expect(screen.getByText("This node defines its own stage ladder.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Revert to inherited" }));

    await waitFor(() => expect(updateStrain).toHaveBeenCalled());
    const [strainId, patch] = updateStrain.mock.calls[0] as unknown as [
      string,
      { phenology_stages_override: null },
    ];
    expect(strainId).toBe(A1.id);
    expect(patch.phenology_stages_override).toBeNull();
  });

  // The field that made `gdd_from_planting` unusable: accepted by the API
  // since the taxonomy landed, never rendered by any control.
  it("writes the GDD base temperature, which had no control anywhere", async () => {
    const user = userEvent.setup();
    renderAt("?node=wheat&tab=details");

    const gdd = await screen.findByLabelText("GDD base temperature (°C)");
    await user.type(gdd, "5");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(updateCrop).toHaveBeenCalled());
    const [cropId, patch] = updateCrop.mock.calls[0] as unknown as [
      string,
      { gdd_base_temp_c: number | null },
    ];
    expect(cropId).toBe(WHEAT.id);
    expect(patch.gdd_base_temp_c).toBe(5);
  });
});

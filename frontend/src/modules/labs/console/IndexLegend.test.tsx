import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import type { GridCellWithValue } from "@/api/grid";
import { setupTestI18n } from "@/i18n/testing";
import { PrefsProvider } from "@/prefs/PrefsContext";
import { IndexLegend } from "./IndexLegend";
import type { LegendGroup } from "./legendBins";

function cell(mean: string | null, areaM2: string, id: string): GridCellWithValue {
  return {
    cell_id: id,
    row_idx: 0,
    col_idx: 0,
    area_m2: areaM2,
    centroid_lon: 32.6,
    centroid_lat: 30.0,
    geometry: { type: "Polygon", coordinates: [] },
    mean,
    valid_pixel_pct: "100",
    time: "2026-07-01T00:00:00Z",
  };
}

const GROUPS: LegendGroup[] = [
  { blockId: "b1", cells: [cell("0.25", "42008.3", "c1"), cell(null, "4200.83", "c2")] },
];

function renderLegend(props: Partial<Parameters<typeof IndexLegend>[0]> = {}) {
  return render(
    <PrefsProvider>
      <IndexLegend
        groups={GROUPS}
        code="ndvi"
        scopeBlockId={null}
        scopeBlockName={null}
        showGrid
        griddedCount={1}
        imagerySubCount={1}
        loading={false}
        {...props}
      />
    </PrefsProvider>,
  );
}

describe("IndexLegend", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
  });

  it("names the index and its agronomic family", () => {
    renderLegend();
    expect(screen.getByText("NDVI")).toBeInTheDocument();
    expect(screen.getByText("Vigour & canopy")).toBeInTheDocument();
  });

  it("renders one row per band with a class label", () => {
    renderLegend();
    // ndvi has six bands; "Sparse canopy" is the one holding 0.25.
    expect(screen.getByText("Sparse canopy")).toBeInTheDocument();
    expect(screen.getByText("Very dense")).toBeInTheDocument();
    expect(screen.getByText("Bare soil")).toBeInTheDocument();
  });

  it("reports covered area in the user's unit, defaulting to feddan", () => {
    renderLegend();
    // 42008.3 m² is exactly 10 feddan; the no-reading cell is excluded.
    expect(screen.getByText("Covered")).toBeInTheDocument();
    expect(screen.getAllByText("10.0").length).toBeGreaterThan(0);
  });

  it("reports cells with no reading separately, and does not call them cloud", () => {
    renderLegend();
    expect(screen.getByText("No reading")).toBeInTheDocument();
    expect(screen.queryByText(/cloud/i)).not.toBeInTheDocument();
  });

  it("shows the index-choice hint on the band our own copy flags", () => {
    renderLegend();
    expect(screen.getByText(/Better read with NDRE/)).toBeInTheDocument();
  });

  it("says the farm has no imagery when nothing is subscribed", () => {
    // The Bashayer case: blocks exist, none has a subscription, so none has
    // a grid. The legend must name the upstream cause, not "no grid".
    renderLegend({ groups: undefined, griddedCount: 0, imagerySubCount: 0 });
    expect(screen.getByText("No imagery subscription")).toBeInTheDocument();
    expect(screen.queryByText("Covered")).not.toBeInTheDocument();
  });

  it("says no grid is configured when imagery exists but zoning does not", () => {
    renderLegend({ groups: undefined, griddedCount: 0, imagerySubCount: 4 });
    expect(screen.getByText("No zoned blocks on this farm")).toBeInTheDocument();
  });

  it("says the overlay is off rather than showing an empty scale", () => {
    renderLegend({ showGrid: false });
    expect(screen.getByText("Grid overlay is off")).toBeInTheDocument();
  });

  it("scopes to the selected block when one is chosen", () => {
    renderLegend({ scopeBlockId: "b1", scopeBlockName: "B-14 Ridge" });
    expect(screen.getByText("B-14 Ridge only")).toBeInTheDocument();
  });

  it("renders in Arabic", async () => {
    await setupTestI18n("ar");
    renderLegend();
    expect(screen.getByText("غطاء متناثر")).toBeInTheDocument();
    expect(screen.getByText("بدون قراءة")).toBeInTheDocument();
  });
});

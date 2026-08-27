import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { GridCellPopup } from "./GridCellPopup";

// One empty cell and a farm of empty cells printed the same "—". That is
// how a farm whose grid backfill never ran looked identical to a cell under
// cloud, for as long as nobody went looking. The popup now says which one
// it is, and these hold that apart.

vi.mock("../../api/grid", () => ({
  getGridCellHistory: () => Promise.resolve({ points: [] }),
}));

function wrap(node: ReactNode): ReactNode {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{node}</QueryClientProvider>;
}

const BASE = {
  open: true as const,
  cellId: "c1",
  productId: "p1",
  indexCode: "ndvi" as const,
  lat: 30.001,
  lon: 31.201,
  blockName: "BA",
  x: 10,
  y: 10,
  time: null,
  baselineMean: null,
  z: null,
  onClose: () => {},
};

describe("GridCellPopup", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
  });

  it("says the farm has no readings when nothing anywhere has one", async () => {
    render(wrap(<GridCellPopup {...BASE} value={null} farmHasCellReadings={false} />));
    expect(await screen.findByText(/No cell readings for this farm yet/i)).toBeTruthy();
  });

  it("stays quiet for a single empty cell on a farm that does have readings", () => {
    render(wrap(<GridCellPopup {...BASE} value={null} farmHasCellReadings />));
    expect(screen.queryByText(/No cell readings for this farm yet/i)).toBeNull();
    // The dash is still the right answer here: this cell, this date. The
    // popup prints several (headline, min/mean/max, baseline), so this
    // asserts presence rather than a single node.
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("stays quiet when this cell has a reading", () => {
    render(wrap(<GridCellPopup {...BASE} value={0.42} farmHasCellReadings={false} />));
    expect(screen.queryByText(/No cell readings for this farm yet/i)).toBeNull();
    expect(screen.getByText("0.420")).toBeTruthy();
  });

  it("defaults to quiet, so an unwired caller cannot cry wolf", () => {
    render(wrap(<GridCellPopup {...BASE} value={null} />));
    expect(screen.queryByText(/No cell readings for this farm yet/i)).toBeNull();
  });
});

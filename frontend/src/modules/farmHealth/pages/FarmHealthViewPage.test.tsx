// Composition test for the Farm Health View shell.
//
// The rail's rules have their own pure tests in lib/blockRows.test.ts. What
// this proves is what those cannot: that the page mounts against the real
// loaders and that the words a reader sees are the right words.
//
// Every assertion here reads rendered text. The Farm Timeline shipped four
// defects with 46 green tests because each one asserted the layer below the
// bug — props handed to a stubbed map, payloads instead of strings.

/* eslint-disable @typescript-eslint/require-await */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { BlockVerdicts, StatusCode, Verdict } from "@/api/farmHealth";
import { setupTestI18n } from "@/i18n/testing";
import { FarmHealthViewPage } from "./FarmHealthViewPage";

vi.mock("react-oidc-context", () => ({ useAuth: () => ({ user: { access_token: "" } }) }));
vi.mock("@/rbac/useCapability", () => ({ useCapability: () => true }));

// MapLibre reaches for WebGL on construction and jsdom has none. The map has
// its own pure tests in lib/cellRaster.test.ts; what the page owes is the
// join it hands over, so the stub records the props and renders a marker.
const mapProps = vi.hoisted(() => ({ current: null as Record<string, unknown> | null }));
vi.mock("../components/HealthMap", () => ({
  HealthMap: (props: Record<string, unknown>) => {
    mapProps.current = props;
    return <div data-testid="health-map" />;
  },
}));

const grid = vi.hoisted((): { current: unknown } => ({ current: null }));

vi.mock("@/api/grid", () => ({
  getFarmGridCells: vi.fn(async () => grid.current),
}));

/** A square cell polygon at (row, col). Geometry only; no verdict. */
function gridCell(cellId: string, row: number, col: number) {
  const size = 0.001;
  const west = 31 + col * size;
  const south = 30 - row * size;
  return {
    cell_id: cellId,
    row_idx: row,
    col_idx: col,
    area_m2: "100",
    centroid_lon: west,
    centroid_lat: south,
    geometry: {
      type: "Polygon" as const,
      coordinates: [
        [
          [west, south],
          [west + size, south],
          [west + size, south + size],
          [west, south + size],
          [west, south],
        ],
      ],
    },
    mean: null,
    valid_pixel_pct: null,
    time: null,
  };
}

const FARM_ID = "farm-1";

function verdict(blockId: string, treeCode: string, status: StatusCode, cell?: number): Verdict {
  return {
    id: `${blockId}-${treeCode}-${cell ?? "b"}`,
    farm_id: FARM_ID,
    block_id: blockId,
    cell_id: cell === undefined ? null : `cell-${cell}`,
    cell_row: cell === undefined ? null : cell,
    cell_col: cell === undefined ? null : 1,
    scope: cell === undefined ? "block" : "cell",
    tree_id: `tree-${treeCode}`,
    tree_code: treeCode,
    tree_version: 1,
    leaf_node_id: "leaf_ok",
    kind: "status",
    status_code: status,
    severity: null,
    text_en: "Checked.",
    text_ar: null,
    valid_from: "2026-09-01T00:00:00Z",
    valid_to: null,
    last_evaluated_at: "2026-09-07T00:00:00Z",
    alert_id: null,
    recommendation_id: null,
  };
}

function farmBlock(blockId: string, verdicts: Verdict[]): BlockVerdicts {
  return {
    block_id: blockId,
    as_of: null,
    worst_status: null,
    last_evaluated_at: null,
    verdicts,
  };
}

vi.mock("@/api/farms", () => ({
  getFarm: vi.fn(async () => ({ id: FARM_ID, name: "Mango Republic", code: "MR" })),
}));

/** A block polygon. The map needs one or the block is not drawn at all. */
function boundary(index: number) {
  const west = 31 + index * 0.01;
  const south = 30;
  return {
    type: "Polygon" as const,
    coordinates: [
      [
        [west, south],
        [west + 0.005, south],
        [west + 0.005, south + 0.005],
        [west, south + 0.005],
        [west, south],
      ],
    ],
  };
}

vi.mock("@/api/blocks", () => ({
  listBlocks: vi.fn(async () => ({
    items: [
      { id: "b1", code: "AG-R01-C01", name: "North block", boundary: boundary(0) },
      { id: "b2", code: "AG-R01-C02", name: "South block", boundary: boundary(1) },
      { id: "b3", code: "AG-R02-C01", name: "East block", boundary: boundary(2) },
    ],
    next_cursor: null,
  })),
}));

const farmVerdicts = vi.hoisted((): { current: unknown } => ({ current: null }));

vi.mock("@/api/farmHealth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/farmHealth")>();
  return {
    ...actual,
    getVerdictStatuses: vi.fn(async () => [
      { code: "na", rank: 0, color: "#9AA0A6", label_en: "Not assessed", label_ar: "لا ينطبق" },
      { code: "very_good", rank: 1, color: "#1B873F", label_en: "Very good", label_ar: "ممتاز" },
      { code: "good", rank: 2, color: "#6FBF4B", label_en: "Good", label_ar: "جيد" },
      { code: "issue", rank: 3, color: "#E8A33D", label_en: "Issue", label_ar: "مشكلة" },
      { code: "alert", rank: 4, color: "#D64545", label_en: "Alert", label_ar: "إنذار" },
    ]),
    getFarmVerdicts: vi.fn(async () => farmVerdicts.current),
  };
});

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/farm-health/${FARM_ID}`]}>
        <Routes>
          <Route path="/farm-health/:farmId" element={<FarmHealthViewPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("FarmHealthViewPage", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    grid.current = { farm_id: FARM_ID, index_code: "ndvi", blocks: [] };
    farmVerdicts.current = {
      farm_id: FARM_ID,
      as_of: null,
      blocks: [
        farmBlock("b1", [verdict("b1", "t_cwsi", "good")]),
        farmBlock("b2", [
          verdict("b2", "t_cwsi", "alert", 1),
          verdict("b2", "t_cwsi", "good", 2),
        ]),
      ],
    };
  });

  it("lists the blocks worst first, by the words a reader sees", async () => {
    renderPage();

    const rail = await screen.findByRole("list");
    const codes = within(rail)
      .getAllByRole("button")
      .map((button) => within(button).getByText(/AG-/).textContent);
    expect(codes).toEqual(["AG-R01-C02", "AG-R01-C01", "AG-R02-C01"]);
  });

  it("names the status in words, not a code", async () => {
    renderPage();

    // The block holding one alert cell and one good cell reads as Alert.
    expect(await screen.findByText("Alert")).toBeInTheDocument();
    expect(screen.getByText("Good")).toBeInTheDocument();
    expect(screen.queryByText("very_good")).not.toBeInTheDocument();
  });

  it("says a block was never checked, rather than showing it as fine", async () => {
    renderPage();

    // b3 has no verdict row at all. That is not the same as a verdict of
    // "not assessed", and the two must not read alike.
    expect(await screen.findByText("Tree did not run")).toBeInTheDocument();
  });

  it("opens on the worst block and describes it", async () => {
    renderPage();

    const heading = await screen.findByRole("heading", { level: 2 });
    expect(heading).toHaveTextContent("AG-R01-C02");
    expect(screen.getByText(/2 verdicts from t_cwsi\./)).toBeInTheDocument();
  });

  it("lets a reader open a block that the tree never ran on", async () => {
    renderPage();

    const rail = await screen.findByRole("list");
    const target = within(rail)
      .getAllByRole("button")
      .find((button) => button.textContent?.includes("AG-R02-C01"));
    fireEvent.click(target as HTMLElement);

    await waitFor(() => {
      expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("AG-R02-C01");
    });
    expect(
      screen.getByText(/t_cwsi did not run on this block\./),
    ).toBeInTheDocument();
  });

  it("lists only trees that have said something about this farm", async () => {
    farmVerdicts.current = {
      farm_id: FARM_ID,
      as_of: null,
      blocks: [
        farmBlock("b1", [verdict("b1", "t_ndvi", "good"), verdict("b1", "t_cwsi", "alert")]),
      ],
    };
    renderPage();

    const picker = await screen.findByRole("combobox", { name: "Decision tree" });
    const options = within(picker).getAllByRole("option").map((o) => o.textContent);
    expect(options).toEqual(["t_cwsi", "t_ndvi"]);
  });

  it("switching tree re-reads the rail", async () => {
    farmVerdicts.current = {
      farm_id: FARM_ID,
      as_of: null,
      blocks: [
        farmBlock("b1", [verdict("b1", "t_cwsi", "alert"), verdict("b1", "t_ndvi", "good")]),
        farmBlock("b2", [verdict("b2", "t_ndvi", "alert")]),
      ],
    };
    renderPage();

    // t_cwsi sorts first, so it is the default. b1 is its only alert.
    expect(await screen.findByRole("heading", { level: 2 })).toHaveTextContent("AG-R01-C01");

    const picker = screen.getByRole("combobox", { name: "Decision tree" });
    fireEvent.change(picker, { target: { value: "t_ndvi" } });

    // Under t_ndvi the worst block is b2, and the selection follows.
    await waitFor(() => {
      expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("AG-R01-C02");
    });
  });

  it("gives the map a cell only when geometry and a verdict agree", async () => {
    // Geometry comes from the grid read and the colour from the verdict
    // read, joined on cell_id. A cell with geometry and no verdict is left
    // out: the tree did not reach it, and painting it any colour says
    // otherwise.
    grid.current = {
      farm_id: FARM_ID,
      index_code: "ndvi",
      blocks: [
        {
          block_id: "b2",
          product_id: "p1",
          at: null,
          cells: [gridCell("cell-1", 0, 0), gridCell("cell-2", 0, 1), gridCell("cell-3", 0, 2)],
        },
      ],
    };
    farmVerdicts.current = {
      farm_id: FARM_ID,
      as_of: null,
      blocks: [
        farmBlock("b2", [
          { ...verdict("b2", "t_cwsi", "alert", 0), cell_id: "cell-1" },
          { ...verdict("b2", "t_cwsi", "good", 1), cell_id: "cell-2" },
        ]),
      ],
    };
    renderPage();

    await screen.findByTestId("health-map");
    const cells = mapProps.current?.cells as { cellId: string; status: string }[];
    expect(cells.map((c) => c.cellId)).toEqual(["cell-1", "cell-2"]);
    expect(cells.map((c) => c.status)).toEqual(["alert", "good"]);
    // cell-3 has a polygon and no verdict, so it is not painted at all.
    expect(cells.map((c) => c.cellId)).not.toContain("cell-3");
  });

  it("marks the selected block for the map, and only that one", async () => {
    renderPage();

    await screen.findByTestId("health-map");
    const blocks = mapProps.current?.blocks as { blockId: string; selected: boolean }[];
    expect(blocks.filter((b) => b.selected).map((b) => b.blockId)).toEqual(["b2"]);
  });

  it("says so when no tree has run on the farm at all", async () => {
    farmVerdicts.current = { farm_id: FARM_ID, as_of: null, blocks: [] };
    renderPage();

    expect(
      await screen.findByText("No decision tree has recorded a verdict on this farm yet."),
    ).toBeInTheDocument();
  });
});

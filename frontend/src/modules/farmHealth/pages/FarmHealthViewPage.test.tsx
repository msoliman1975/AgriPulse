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
// Which reads are still in flight. The screen must draw without the grid and
// without the history, so a test has to be able to hold them open.
const held = vi.hoisted(() => ({
  grid: false,
  history: false,
  historyFails: false,
  emptyAfterFirstRead: false,
}));
const historyReads = vi.hoisted(() => ({ n: 0 }));
const gridCalls = vi.hoisted(() => vi.fn());

vi.mock("@/api/grid", () => ({
  getFarmGridCells: vi.fn(async () => {
    gridCalls();
    if (held.grid) await new Promise(() => {});
    return grid.current;
  }),
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
    tree_name_en: null,
    tree_name_ar: null,
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
const reasoning = vi.hoisted((): { current: unknown } => ({ current: null }));
const history = vi.hoisted((): { current: unknown } => ({ current: null }));

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
    getVerdictReasoning: vi.fn(async () => reasoning.current),
    getFarmVerdictHistory: vi.fn(async () => {
      if (held.history) await new Promise(() => {});
      if (held.historyFails) throw new Error("history read failed");
      historyReads.n += 1;
      // A later range is a different window, and may hold nothing at all.
      if (held.emptyAfterFirstRead && historyReads.n > 1) {
        return { ...(history.current as Record<string, unknown>), verdicts: [] };
      }
      return history.current;
    }),
  };
});

/** A block with three alert cells, which is what an open area needs. */
function withCells() {
  grid.current = {
    farm_id: FARM_ID,
    index_code: "ndvi",
    blocks: [
      {
        block_id: "b2",
        product_id: "p1",
        at: null,
        cells: [gridCell("c00", 0, 0), gridCell("c01", 0, 1), gridCell("c02", 0, 2)],
      },
    ],
  };
  farmVerdicts.current = {
    farm_id: FARM_ID,
    as_of: null,
    blocks: [
      farmBlock("b2", [
        { ...verdict("b2", "t_cwsi", "alert", 0), id: "v1", cell_id: "c00", leaf_node_id: "leaf_dry" },
        { ...verdict("b2", "t_cwsi", "alert", 1), id: "v2", cell_id: "c01", leaf_node_id: "leaf_dry" },
        { ...verdict("b2", "t_cwsi", "alert", 2), id: "v3", cell_id: "c02", leaf_node_id: "leaf_dry" },
      ]),
    ],
  };
}

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
    held.grid = false;
    held.history = false;
    held.historyFails = false;
    held.emptyAfterFirstRead = false;
    historyReads.n = 0;
    gridCalls.mockClear();
    grid.current = { farm_id: FARM_ID, index_code: "ndvi", blocks: [] };
    history.current = { farm_id: FARM_ID, from_at: "", to_at: "", tree_code: null, truncated: false, verdicts: [] };
    reasoning.current = {
      verdict_id: "v1",
      block_id: "b2",
      cell_id: null,
      cell_row: null,
      cell_col: null,
      scope: "cell",
      tree_id: "tree-1",
      tree_code: "t_cwsi",
      tree_name_en: null,
      tree_name_ar: null,
      tree_version: 1,
      leaf_node_id: "leaf_dry",
      leaf_label_en: "Irrigate within 24 hours",
      leaf_label_ar: "اسقِ خلال 24 ساعة",
      kind: "recommendation",
      status_code: "alert",
      severity: "medium",
      valid_from: "2026-09-01T00:00:00Z",
      last_evaluated_at: "2026-09-07T00:00:00Z",
      reasoning_available: true,
      trace_id: "trace-1",
      evaluated_at: "2026-09-07T00:00:00Z",
      narrative_en:
        "Checked on 2026-09-07. The tree checked 2 things, in this order. " +
        "Is CWSI clipped at the index ceiling? No. So t_cwsi reports Alert.",
      narrative_ar: "تم الفحص في 2026-09-07.",
      text_en: null,
      text_ar: null,
      node_path: [
        {
          node_id: "saturation",
          matched: false,
          label_en: "Is CWSI clipped at the index ceiling?",
          condition: { tree: { op: "ge", right: 0.99 } },
          values: { "indices.cwsi.mean": "0.47" },
        },
        {
          node_id: "medium_check",
          matched: true,
          label_en: "Is CWSI above the medium-tree bound?",
          condition: {
            tree: { op: "gt", right: { source: "params", name: "medium_cwsi_ceiling" } },
          },
          values: { "indices.cwsi.mean": "0.47" },
        },
      ],
      resolved_values: { "indices.cwsi.mean": "0.47" },
      param_overrides: {},
    };
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

    const rail = await screen.findByRole("list");
    // The block holding one alert cell and one good cell reads as Alert.
    expect(within(rail).getByText("Alert")).toBeInTheDocument();
    expect(within(rail).getByText("Good")).toBeInTheDocument();
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
    // The summary counts what the block holds, by status, in words.
    expect(screen.getByText("Block reads")).toBeInTheDocument();
    const counts = screen.getByText("Block reads").closest("div")?.parentElement;
    expect(counts).toHaveTextContent("1");
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

  it("groups the block into named areas instead of listing every cell", async () => {
    // Six cells: three alert in the north row, three good in the south.
    // The screen must offer two areas, not six rows.
    grid.current = {
      farm_id: FARM_ID,
      index_code: "ndvi",
      blocks: [
        {
          block_id: "b2",
          product_id: "p1",
          at: null,
          cells: [
            gridCell("c00", 0, 0),
            gridCell("c01", 0, 1),
            gridCell("c02", 0, 2),
            gridCell("c10", 1, 0),
            gridCell("c11", 1, 1),
            gridCell("c12", 1, 2),
          ],
        },
      ],
    };
    farmVerdicts.current = {
      farm_id: FARM_ID,
      as_of: null,
      blocks: [
        farmBlock("b2", [
          { ...verdict("b2", "t_cwsi", "alert", 0), cell_id: "c00", leaf_node_id: "leaf_dry" },
          { ...verdict("b2", "t_cwsi", "alert", 1), cell_id: "c01", leaf_node_id: "leaf_dry" },
          { ...verdict("b2", "t_cwsi", "alert", 2), cell_id: "c02", leaf_node_id: "leaf_dry" },
          { ...verdict("b2", "t_cwsi", "good", 3), cell_id: "c10", leaf_node_id: "leaf_ok" },
          { ...verdict("b2", "t_cwsi", "good", 4), cell_id: "c11", leaf_node_id: "leaf_ok" },
          { ...verdict("b2", "t_cwsi", "good", 5), cell_id: "c12", leaf_node_id: "leaf_ok" },
        ]),
      ],
    };
    renderPage();

    expect(await screen.findByText("Selected area")).toBeInTheDocument();
    // Each half is 50% of the block, so both are named as most of it, with
    // the direction inside the sentence.
    expect(
      screen.getByRole("button", { name: /Most of the block, toward the north/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Most of the block, toward the south/ }),
    ).toBeInTheDocument();
    // Two areas offered for six cells, not six rows.
    expect(screen.getByText("2 areas.", { exact: false })).toBeInTheDocument();
  });

  it("opens the worst area and says how much of the block it is", async () => {
    grid.current = {
      farm_id: FARM_ID,
      index_code: "ndvi",
      blocks: [
        {
          block_id: "b2",
          product_id: "p1",
          at: null,
          cells: [gridCell("c00", 0, 0), gridCell("c01", 0, 1), gridCell("c02", 0, 2)],
        },
      ],
    };
    farmVerdicts.current = {
      farm_id: FARM_ID,
      as_of: null,
      blocks: [
        farmBlock("b2", [
          { ...verdict("b2", "t_cwsi", "alert", 0), cell_id: "c00", leaf_node_id: "leaf_dry" },
          { ...verdict("b2", "t_cwsi", "alert", 1), cell_id: "c01", leaf_node_id: "leaf_dry" },
          { ...verdict("b2", "t_cwsi", "alert", 2), cell_id: "c02", leaf_node_id: "leaf_dry" },
        ]),
      ],
    };
    renderPage();

    const heading = await screen.findByRole("heading", { level: 3 });
    expect(heading).toHaveTextContent("The whole block");
    expect(screen.getByText(/3 cells · 100% of the block/)).toBeInTheDocument();
  });

  it("outlines the area it has open on the map", async () => {
    grid.current = {
      farm_id: FARM_ID,
      index_code: "ndvi",
      blocks: [
        {
          block_id: "b2",
          product_id: "p1",
          at: null,
          cells: [gridCell("c00", 0, 0), gridCell("c01", 0, 1), gridCell("c02", 0, 2)],
        },
      ],
    };
    farmVerdicts.current = {
      farm_id: FARM_ID,
      as_of: null,
      blocks: [
        farmBlock("b2", [
          { ...verdict("b2", "t_cwsi", "alert", 0), cell_id: "c00", leaf_node_id: "leaf_dry" },
          { ...verdict("b2", "t_cwsi", "alert", 1), cell_id: "c01", leaf_node_id: "leaf_dry" },
          { ...verdict("b2", "t_cwsi", "alert", 2), cell_id: "c02", leaf_node_id: "leaf_dry" },
        ]),
      ],
    };
    renderPage();

    await screen.findByTestId("health-map");
    const highlighted = mapProps.current?.highlighted as Set<string>;
    expect([...highlighted].sort()).toEqual(["c00", "c01", "c02"]);
  });

  it("says a block has no cell verdicts rather than showing an empty list", async () => {
    // The tree ran and answered for the whole block, so there are verdicts
    // but no cells. An empty area list with no words reads as a broken page.
    renderPage();

    expect(
      await screen.findByText("This block has no cell verdicts for this tree."),
    ).toBeInTheDocument();
  });

  it("keeps the reasoning closed until it is asked for", async () => {
    // It is a follow-up question, not the answer. Opening by default would
    // push the map off the screen on every block.
    withCells();
    renderPage();

    const link = await screen.findByRole("button", { name: "Show how this was decided" });
    expect(link).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Steps the tree took, root to leaf")).not.toBeInTheDocument();
  });

  it("shows the walk in place, with each step's reading and test", async () => {
    withCells();
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Show how this was decided" }));

    // The paragraph is what the card leads with now; the grid moved behind
    // its own toggle, for the reader auditing a threshold.
    expect(
      await screen.findByText(/The tree checked 2 things, in this order/),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show the checks as a table" }));

    expect(await screen.findByText("Steps the tree took, root to leaf")).toBeInTheDocument();
    // The question, the value it read, and what it was compared with — the
    // three things that answer "why this colour".
    expect(screen.getByText("Is CWSI above the medium-tree bound?")).toBeInTheDocument();
    // Both steps read the same index, and each says so on its own row.
    expect(screen.getAllByText(/read indices\.cwsi\.mean = 0\.47/)).toHaveLength(2);
    expect(screen.getByText(/test > medium_cwsi_ceiling/)).toBeInTheDocument();
    // It expands in the page. A dialog is what this replaced.
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("says the walk is gone rather than showing no steps", async () => {
    // Retention prunes eval runs. An empty step list would read as "the tree
    // did nothing", which is a different and wrong sentence.
    reasoning.current = {
      ...(reasoning.current as Record<string, unknown>),
      reasoning_available: false,
      trace_id: null,
      node_path: [],
    };
    withCells();
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Show how this was decided" }));

    expect(
      await screen.findByText(/The walk behind this verdict is no longer kept/),
    ).toBeInTheDocument();
    expect(screen.queryByText("Steps the tree took, root to leaf")).not.toBeInTheDocument();
  });

  it("opens on the newest day, with nothing further forward to go", async () => {
    renderPage();

    const latest = await screen.findByRole("button", { name: "Latest" });
    // Already there, so the way back is off.
    expect(latest).toBeDisabled();
    expect(screen.getByRole("combobox", { name: "Range" })).toHaveValue("30");
  });

  it("shows a past day from the intervals, not from the live read", async () => {
    // The live read says the block is good today. The history says it was an
    // alert a week ago. Stepping back must show the alert; showing today's
    // answer on an earlier date is the failure this guards.
    const weekAgo = new Date(Date.now() - 7 * 86_400_000).toISOString();
    const twoDaysAgo = new Date(Date.now() - 2 * 86_400_000).toISOString();
    history.current = {
      farm_id: FARM_ID,
      from_at: "",
      to_at: "",
      tree_code: null,
      tree_name_en: null,
      tree_name_ar: null,
      truncated: false,
      verdicts: [
        {
          ...verdict("b1", "t_cwsi", "alert"),
          id: "old",
          valid_from: weekAgo,
          valid_to: twoDaysAgo,
        },
      ],
    };
    farmVerdicts.current = {
      farm_id: FARM_ID,
      as_of: null,
      blocks: [farmBlock("b1", [verdict("b1", "t_cwsi", "good")])],
    };
    renderPage();

    const scrubber = await screen.findByRole("slider", { name: "Date" });
    // 30-day window, newest is index 29; five days back lands inside the
    // interval that closed two days ago.
    fireEvent.change(scrubber, { target: { value: "24" } });

    const rail = await screen.findByRole("list");
    await waitFor(() => {
      expect(within(rail).getByText("Alert")).toBeInTheDocument();
    });
  });

  it("changing the range jumps to the newest day of the new window", async () => {
    renderPage();

    const scrubber = await screen.findByRole("slider", { name: "Date" });
    fireEvent.change(scrubber, { target: { value: "3" } });
    expect(screen.getByRole("button", { name: "Latest" })).toBeEnabled();

    fireEvent.change(screen.getByRole("combobox", { name: "Range" }), {
      target: { value: "365" },
    });

    // A new window opens on its newest day, whatever was showing before.
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Latest" })).toBeDisabled();
    });
    expect(screen.getByRole("slider", { name: "Date" })).toHaveAttribute("max", "364");
  });

  it("editing a date asks for a custom range", async () => {
    renderPage();

    const from = await screen.findByLabelText("From");
    fireEvent.change(from, { target: { value: "2026-01-01" } });

    await waitFor(() => {
      expect(screen.getByRole("combobox", { name: "Range" })).toHaveValue("custom");
    });
  });

  it("says when the window holds more history than it can draw", async () => {
    history.current = {
      farm_id: FARM_ID,
      from_at: "",
      to_at: "",
      tree_code: null,
      tree_name_en: null,
      tree_name_ar: null,
      truncated: true,
      verdicts: [],
    };
    renderPage();

    expect(
      await screen.findByText(/more history than the replay can draw/),
    ).toBeInTheDocument();
  });

  it("frames the selected block by default", async () => {
    renderPage();

    await screen.findByTestId("health-map");
    expect(mapProps.current?.fitMode).toBe("block");
    expect(screen.getByRole("button", { name: "Fit block" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("frames the whole farm when asked, and stops greying the other blocks", async () => {
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Whole farm" }));

    await waitFor(() => {
      expect(mapProps.current?.fitMode).toBe("farm");
    });
    expect(screen.getByRole("button", { name: "Whole farm" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("frames the open area when asked", async () => {
    withCells();
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Fit selected area" }));

    await waitFor(() => {
      expect(mapProps.current?.fitMode).toBe("area");
    });
  });

  it("returns to the block when one is picked from the rail", async () => {
    // Clicking a block while looking at the whole farm is a request to look
    // at that block, not to stay zoomed out.
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Whole farm" }));
    await waitFor(() => {
      expect(mapProps.current?.fitMode).toBe("farm");
    });

    const rail = await screen.findByRole("list");
    const target = within(rail)
      .getAllByRole("button")
      .find((button) => button.textContent?.includes("AG-R02-C01"));
    fireEvent.click(target as HTMLElement);

    await waitFor(() => {
      expect(mapProps.current?.fitMode).toBe("block");
    });
  });

  it("refits when the open area changes, not when one is merely hovered", async () => {
    // The fit key carries the chosen area. Hovering a chip previews it on
    // the map, and flying the camera on hover would make the map unusable.
    withCells();
    renderPage();

    await screen.findByTestId("health-map");
    const before = mapProps.current?.fitKey;
    const chip = screen.getAllByRole("button", { name: /cells/ })[0];
    fireEvent.mouseEnter(chip);

    await waitFor(() => {
      expect(mapProps.current?.fitKey).toBe(before);
    });
  });

  it("names the tree in the picker, and keeps the code as the value", async () => {
    // The picker listed `t_cwsi` and `t_ndvi`. Those are authoring handles.
    farmVerdicts.current = {
      farm_id: FARM_ID,
      as_of: null,
      blocks: [
        farmBlock("b1", [
          { ...verdict("b1", "t_cwsi", "alert"), tree_name_en: "Mango water stress" },
          { ...verdict("b1", "t_ndvi", "good"), tree_name_en: "Canopy vigour" },
        ]),
      ],
    };
    renderPage();

    const picker = await screen.findByRole("combobox", { name: "Decision tree" });
    const options = within(picker).getAllByRole("option");
    expect(options.map((option) => option.textContent)).toEqual([
      "Canopy vigour",
      "Mango water stress",
    ]);
    // The value is still the code: it is what a verdict row carries.
    expect(options.map((option) => (option as HTMLOptionElement).value)).toEqual([
      "t_ndvi",
      "t_cwsi",
    ]);
  });

  it("names the tree when saying it did not run, not its code", async () => {
    farmVerdicts.current = {
      farm_id: FARM_ID,
      as_of: null,
      blocks: [
        farmBlock("b1", [
          { ...verdict("b1", "t_cwsi", "good"), tree_name_en: "Mango water stress" },
        ]),
      ],
    };
    renderPage();

    const rail = await screen.findByRole("list");
    const target = within(rail)
      .getAllByRole("button")
      .find((button) => button.textContent?.includes("AG-R02-C01"));
    fireEvent.click(target as HTMLElement);

    expect(
      await screen.findByText(/Mango water stress did not run on this block\./),
    ).toBeInTheDocument();
  });

  it("names the leaf the tree reached, not its node id", async () => {
    // `leaf_dry` is an authoring handle, printed on the one line that states
    // the answer. So were the kind and the status, as database codes.
    withCells();
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Show how this was decided" }));

    expect(await screen.findByText(/Irrigate within 24 hours/)).toBeInTheDocument();
    expect(screen.queryByText(/leaf_dry/)).not.toBeInTheDocument();
    // The kind and the status are words on the same line.
    // The kind and the status ride the same line, and were codes too. This
    // verdict is a status leaf, so "kind status" is the honest reading.
    expect(screen.getByText(/kind status · status Alert/)).toBeInTheDocument();
  });

  it("shows the day on the map rather than beside the controls", async () => {
    renderPage();

    const caption = await screen.findByTestId("farm-health-map-date");
    // A real date, formatted, not an ISO string or a day number.
    expect(caption.textContent).toMatch(/\d{4}/);
  });

  it("puts the replay controls under the map, not above it", async () => {
    renderPage();

    const map = await screen.findByTestId("health-map");
    const range = screen.getByRole("combobox", { name: "Range" });
    // DOCUMENT_POSITION_FOLLOWING: the range control comes after the map.
    expect(map.compareDocumentPosition(range) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("offers a handle for the block list and one for the map", async () => {
    renderPage();

    expect(await screen.findByRole("separator", { name: "Block list width" })).toBeInTheDocument();
    expect(screen.getByRole("separator", { name: "Map height" })).toBeInTheDocument();
  });

  it("resizes the block list from the keyboard", async () => {
    renderPage();

    const handle = await screen.findByRole("separator", { name: "Block list width" });
    const before = Number(handle.getAttribute("aria-valuenow"));
    fireEvent.keyDown(handle, { key: "ArrowRight" });

    await waitFor(() => {
      expect(Number(handle.getAttribute("aria-valuenow"))).toBeGreaterThan(before);
    });
  });

  it("draws the farm without waiting for the grid or the history", async () => {
    // Both reads were in the loading gate. On a farm whose trees all answer
    // per block the grid was fetched, waited for, and never used.
    held.grid = true;
    held.history = true;
    withCells();
    renderPage();

    const rail = await screen.findByRole("list");
    expect(within(rail).getAllByRole("button").length).toBeGreaterThan(0);
    expect(await screen.findByTestId("health-map")).toBeInTheDocument();
  });

  it("does not read the grid at all when every verdict is block-scoped", async () => {
    // The heaviest call on the screen, for geometry nothing would join to.
    farmVerdicts.current = {
      farm_id: FARM_ID,
      as_of: null,
      blocks: [farmBlock("b1", [verdict("b1", "t_cwsi", "good")])],
    };
    renderPage();

    await screen.findByTestId("health-map");
    await waitFor(() => {
      expect(screen.getByRole("heading", { level: 2 })).toBeInTheDocument();
    });
    expect(gridCalls).not.toHaveBeenCalled();
  });

  it("holds the replay until the history it would draw has landed", async () => {
    // Scrubbing without the intervals would draw today's verdicts under an
    // older date — a wrong map that looks entirely plausible.
    held.history = true;
    renderPage();

    const scrubber = await screen.findByRole("slider", { name: "Date" });
    expect(scrubber).toBeDisabled();
    expect(screen.getByRole("button", { name: "Play the replay" })).toBeDisabled();
    expect(screen.getByText(/Loading the history for this range/)).toBeInTheDocument();
  });

  it("keeps a tree in the picker that only spoke earlier in the window", async () => {
    // Built from the live read alone, the picker loses the tree that ran in
    // June and stopped — which is the tree someone opens a replay to look
    // at. Built from the frame on show, it rewrites itself mid-replay.
    const weekAgo = new Date(Date.now() - 7 * 86_400_000).toISOString();
    const twoDaysAgo = new Date(Date.now() - 2 * 86_400_000).toISOString();
    history.current = {
      farm_id: FARM_ID,
      from_at: "",
      to_at: "",
      tree_code: null,
      truncated: false,
      verdicts: [
        {
          ...verdict("b1", "t_retired", "alert"),
          id: "old",
          tree_name_en: "Retired tree",
          valid_from: weekAgo,
          valid_to: twoDaysAgo,
        },
      ],
    };
    farmVerdicts.current = {
      farm_id: FARM_ID,
      as_of: null,
      blocks: [
        farmBlock("b1", [
          { ...verdict("b1", "t_cwsi", "good"), tree_name_en: "Water stress" },
        ]),
      ],
    };
    renderPage();

    const picker = await screen.findByRole("combobox", { name: "Decision tree" });
    await waitFor(() => {
      expect(
        within(picker)
          .getAllByRole("option")
          .map((option) => option.textContent),
      ).toEqual(["Retired tree", "Water stress"]);
    });
  });

  it("stops saying it is reading the grid on a farm that has none", async () => {
    // `getFarmGridCells` resolves to NULL on a 404. Gating the message on
    // the absence of data rather than on the read would leave the panel
    // under "reading the cell grid" for ever.
    grid.current = null;
    farmVerdicts.current = {
      farm_id: FARM_ID,
      as_of: null,
      blocks: [
        farmBlock("b2", [{ ...verdict("b2", "t_cwsi", "alert", 0), cell_id: "cell-1" }]),
      ],
    };
    renderPage();

    expect(
      await screen.findByText("This block has no cell verdicts for this tree."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Reading the block's cell grid/)).not.toBeInTheDocument();
  });

  it("keeps the replay off, and says why, when the history cannot be read", async () => {
    // A failed read resolves to an empty list. A replay drawn from that
    // paints every block "tree did not run" on every past day — a wrong map
    // with nothing on screen to say that anything failed.
    held.historyFails = true;
    renderPage();

    const scrubber = await screen.findByRole("slider", { name: "Date" });
    await waitFor(() => {
      expect(scrubber).toBeDisabled();
    });
    expect(
      screen.getByText(/The history for this range could not be read/),
    ).toBeInTheDocument();
    // Today's answers are unaffected, and the screen still shows them.
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("AG-R01-C02");
  });

  it("reads the grid for a per-cell tree that only ran earlier in the window", async () => {
    // A farm turns a per-cell tree off. Its verdicts all close, so the live
    // read has none — but the replay still paints its cells on the days it
    // ran, and without the grid there is no geometry to paint them on.
    const weekAgo = new Date(Date.now() - 7 * 86_400_000).toISOString();
    const twoDaysAgo = new Date(Date.now() - 2 * 86_400_000).toISOString();
    history.current = {
      farm_id: FARM_ID,
      from_at: "",
      to_at: "",
      tree_code: null,
      truncated: false,
      verdicts: [
        {
          ...verdict("b2", "t_retired", "alert", 0),
          id: "old",
          cell_id: "cell-1",
          valid_from: weekAgo,
          valid_to: twoDaysAgo,
        },
      ],
    };
    farmVerdicts.current = {
      farm_id: FARM_ID,
      as_of: null,
      blocks: [farmBlock("b1", [verdict("b1", "t_cwsi", "good")])],
    };
    renderPage();

    await screen.findByTestId("health-map");
    await waitFor(() => {
      expect(gridCalls).toHaveBeenCalled();
    });
  });

  it("does not move the chosen tree when the history lands", async () => {
    // The history arrives after the first paint. A history-only tree whose
    // name sorts first must not take the selection: the screen opens on the
    // newest day, where it has nothing to say, so every block would suddenly
    // read "tree did not run".
    history.current = {
      farm_id: FARM_ID,
      from_at: "",
      to_at: "",
      tree_code: null,
      truncated: false,
      verdicts: [
        {
          ...verdict("b1", "t_alpha", "alert"),
          id: "old",
          tree_name_en: "Alpha retired",
          valid_from: new Date(Date.now() - 7 * 86_400_000).toISOString(),
          valid_to: new Date(Date.now() - 2 * 86_400_000).toISOString(),
        },
      ],
    };
    farmVerdicts.current = {
      farm_id: FARM_ID,
      as_of: null,
      blocks: [
        farmBlock("b1", [{ ...verdict("b1", "t_zulu", "good"), tree_name_en: "Zulu live" }]),
      ],
    };
    renderPage();

    const picker = await screen.findByRole("combobox", { name: "Decision tree" });
    // Both are offered, Alpha first by name...
    await waitFor(() => {
      expect(within(picker).getAllByRole("option")).toHaveLength(2);
    });
    // ...and the live one is still the one selected.
    expect(picker).toHaveValue("t_zulu");
  });

  it("keeps an option for the chosen tree when its window stops holding it", async () => {
    // Changing the range re-reads the history. A controlled select whose
    // value matches no option renders as an empty box.
    held.emptyAfterFirstRead = true;
    history.current = {
      farm_id: FARM_ID,
      from_at: "",
      to_at: "",
      tree_code: null,
      truncated: false,
      verdicts: [
        {
          ...verdict("b1", "t_retired", "alert"),
          id: "old",
          tree_name_en: "Retired tree",
          valid_from: new Date(Date.now() - 7 * 86_400_000).toISOString(),
          valid_to: new Date(Date.now() - 2 * 86_400_000).toISOString(),
        },
      ],
    };
    farmVerdicts.current = {
      farm_id: FARM_ID,
      as_of: null,
      blocks: [
        farmBlock("b1", [{ ...verdict("b1", "t_cwsi", "good"), tree_name_en: "Water stress" }]),
      ],
    };
    renderPage();

    const picker = await screen.findByRole("combobox", { name: "Decision tree" });
    await waitFor(() => {
      expect(within(picker).getAllByRole("option")).toHaveLength(2);
    });
    fireEvent.change(picker, { target: { value: "t_retired" } });

    fireEvent.change(screen.getByRole("combobox", { name: "Range" }), {
      target: { value: "365" },
    });

    // The new window holds nothing from that tree, and the picker still
    // offers it rather than showing a blank box.
    await waitFor(() => {
      expect(screen.getByRole("slider", { name: "Date" })).toHaveAttribute("max", "364");
    });
    expect(picker).toHaveValue("t_retired");
    expect(
      within(picker)
        .getAllByRole("option")
        .map((option) => (option as HTMLOptionElement).value),
    ).toContain("t_retired");
  });

  it("says so when no tree has run on the farm at all", async () => {
    farmVerdicts.current = { farm_id: FARM_ID, as_of: null, blocks: [] };
    renderPage();

    expect(
      await screen.findByText("No decision tree has recorded a verdict on this farm yet."),
    ).toBeInTheDocument();
  });
});

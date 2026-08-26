// Composition test for the Farm Timeline shell.
//
// The frame arithmetic and the mark building have their own pure tests.
// What this proves is the part neither of those can: that the three zones
// mount together against the real loaders, that the play head moves the
// rail and the map in step, and that scrubbing to a date with nothing on
// it says so rather than showing yesterday's list.

// `vi.fn(async () => fixture)` is the idiomatic mock shape for an async
// api function: it has nothing to await, but it must return a promise.
/* eslint-disable @typescript-eslint/require-await */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";
import { PrefsProvider } from "@/prefs/PrefsContext";
import { FarmTimelinePage } from "./FarmTimelinePage";

vi.mock("react-oidc-context", () => ({ useAuth: () => ({ user: { access_token: "" } }) }));
vi.mock("@/rbac/useCapability", () => ({ useCapability: () => true }));

// MapLibre reaches for WebGL on construction and jsdom has none. The
// shell's job is to hand the canvas the right props, which the assertions
// below read off this stub rather than off a rendered tile.
const mapProps = vi.hoisted(() => ({ current: null as Record<string, unknown> | null }));
vi.mock("../components/TimelineMap", () => ({
  TimelineMap: (props: Record<string, unknown>) => {
    mapProps.current = props;
    return <div data-testid="timeline-map" />;
  },
}));

const WINDOW_FROM = "2026-06-01";
const WINDOW_TO = "2026-06-10";

const fixtures = vi.hoisted(() => ({
  farm: {
    id: "f1",
    code: "BASH",
    name: "Bashayer El Kheir",
    boundary: null,
  },
  blocks: [
    {
      id: "b1",
      code: "B-01",
      name: "North ridge",
      unit_type: "block",
      boundary: {
        type: "Polygon",
        coordinates: [
          [
            [31.6, 30.6],
            [31.61, 30.6],
            [31.61, 30.61],
            [31.6, 30.61],
            [31.6, 30.6],
          ],
        ],
      },
    },
  ],
  events: [
    {
      kind: "alert",
      id: "a1",
      at: "2026-06-03T09:00:00Z",
      day: "2026-06-03",
      block_id: "b1",
      block_name: "North ridge",
      block_code: "B-01",
      code: "inspect",
      title_en: "NDVI fell 22% in seven days",
      title_ar: null,
      detail: "ndvi_drop",
      severity: "critical",
      point: null,
    },
    {
      kind: "activity",
      id: "p1",
      at: "2026-06-09T06:00:00Z",
      day: "2026-06-09",
      block_id: "b1",
      block_name: "North ridge",
      block_code: "B-01",
      code: "spraying",
      title_en: "Copper",
      title_ar: null,
      detail: null,
      severity: null,
      point: null,
    },
  ],
}));

vi.mock("@/api/farms", () => ({ getFarm: vi.fn(async () => fixtures.farm) }));
vi.mock("@/api/blocks", () => ({
  listBlocks: vi.fn(async () => ({ items: fixtures.blocks, next_cursor: null })),
}));
vi.mock("@/api/imagery", () => ({
  listFarmScenes: vi.fn(async () => ({
    farm_id: "f1",
    median_gap_days: 5,
    items: [
      {
        scene_date: "2026-06-02",
        at: "2026-06-02T08:30:00Z",
        block_count: 1,
        succeeded_count: 1,
        skipped_cloud_count: 0,
        computed_count: 1,
        cloud_cover_pct: "1.0",
      },
    ],
  })),
  listFarmSceneAssets: vi.fn(async () => ({
    farm_id: "f1",
    at: "2026-06-02T08:30:00Z",
    farm: null,
    items: [
      {
        block_id: "b1",
        product_id: "prod",
        stac_item_id: "sentinel_hub/s2l2a/SCENE/aoihash",
        scene_datetime: "2026-06-02T08:30:00Z",
        resolution_m: "10",
      },
    ],
  })),
}));
vi.mock("@/api/insights", () => ({
  getFarmIndexTimeseries: vi.fn(async () => ({
    farm_id: "f1",
    index_code: "ndvi",
    granularity: "daily",
    points: [
      { time: "2026-06-02T00:00:00Z", block_id: "b1", block_name: "North ridge", value: "0.41" },
      { time: "2026-06-07T00:00:00Z", block_id: "b1", block_name: "North ridge", value: "0.38" },
    ],
  })),
}));
vi.mock("@/api/timeline", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/timeline")>();
  return {
    ...actual,
    getFarmTimeline: vi.fn(async () => ({
      farm_id: "f1",
      block_id: null,
      from: WINDOW_FROM,
      to: WINDOW_TO,
      events: fixtures.events,
      days: [
        { day: "2026-06-03", counts: { alert: 1 }, total: 1 },
        { day: "2026-06-09", counts: { activity: 1 }, total: 1 },
      ],
      omitted_kinds: ["recommendation"],
      truncated: false,
    })),
  };
});
vi.mock("@/config/ConfigContext", () => ({
  useOptionalConfig: () => ({
    config: { tile_server_base_url: "https://tiles.test", s3_bucket: "bucket" },
    loading: false,
    error: null,
  }),
}));

/** Set a date input the way a change event would, bypassing typing. */
function setInput(el: HTMLElement, value: string): void {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")!.set!;
  setter.call(el, value);
  el.dispatchEvent(new Event("input", { bubbles: true }));
}

function renderPage(): void {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <PrefsProvider>
        <MemoryRouter initialEntries={["/timeline/f1"]}>
          <Routes>
            <Route path="/timeline/:farmId" element={<FarmTimelinePage />} />
          </Routes>
        </MemoryRouter>
      </PrefsProvider>
    </QueryClientProvider>,
  );
}

/**
 * Render, then drive the header bar to the fixture's window.
 *
 * The page opens on its own default (the last 90 days from today), which
 * would put the June fixtures outside every frame. Setting the dates
 * through the real controls is also the only thing that exercises them.
 */
async function renderAtFixtureWindow(): Promise<void> {
  renderPage();
  await waitFor(() => expect(screen.getByLabelText("From")).toBeInTheDocument());
  setInput(screen.getByLabelText("To"), WINDOW_TO);
  setInput(screen.getByLabelText("From"), WINDOW_FROM);
  await waitFor(() => expect(scrubber().max).toBe("9"));
}

/** The scrubber's range input — the one control that moves the replay. */
function scrubber(): HTMLInputElement {
  return screen.getByRole("slider");
}

function seekTo(day: string): void {
  const input = scrubber();
  const frames = Number(input.max) + 1;
  const start = new Date(`${WINDOW_FROM}T00:00:00Z`).getTime();
  const index = Math.round((new Date(`${day}T00:00:00Z`).getTime() - start) / 86_400_000);
  expect(index).toBeGreaterThanOrEqual(0);
  expect(index).toBeLessThan(frames);
  // `fireEvent`-style set, because a range input does not respond to typing.
  setInput(input, String(index));
}

describe("FarmTimelinePage", () => {
  beforeEach(async () => {
    mapProps.current = null;
    await setupTestI18n("en");
  });

  it("mounts the map, the rail and the scrubber together", async () => {
    renderPage();
    expect(await screen.findByTestId("timeline-map")).toBeInTheDocument();
    expect(scrubber()).toBeInTheDocument();
    await waitFor(() => expect(mapProps.current).not.toBeNull());
  });

  it("opens on the most recent day in the window, not the oldest", async () => {
    // A screen that opens on frame 0 shows a three-month-old picture under
    // today's controls, and nothing on it says so.
    renderPage();
    await waitFor(() => expect(scrubber().value).toBe(scrubber().max));
  });

  it("shows the day's datapoint in the rail when the play head reaches it", async () => {
    await renderAtFixtureWindow();
    seekTo("2026-06-03");
    expect(await screen.findByText("NDVI fell 22% in seven days")).toBeInTheDocument();
  });

  it("drops a datapoint once it is past the fade window", async () => {
    await renderAtFixtureWindow();
    seekTo("2026-06-03");
    expect(await screen.findByText("NDVI fell 22% in seven days")).toBeInTheDocument();
    // Six days later is well past the three-day fade.
    seekTo("2026-06-09");
    await waitFor(() =>
      expect(screen.queryByText("NDVI fell 22% in seven days")).not.toBeInTheDocument(),
    );
    expect(screen.getByText("Copper")).toBeInTheDocument();
  });

  it("hands the map a mark for the alert and none for the activity", async () => {
    await renderAtFixtureWindow();
    seekTo("2026-06-03");
    await waitFor(() => {
      const marks = mapProps.current?.marks as { features: unknown[] };
      expect(marks.features).toHaveLength(1);
    });

    seekTo("2026-06-09");
    await waitFor(() => {
      const marks = mapProps.current?.marks as { features: unknown[] };
      // A completed activity is a property of the block, not of a spot in
      // it — so it lights the block outline instead of dropping a pin.
      expect(marks.features).toHaveLength(0);
      const blocks = mapProps.current?.blocks as {
        features: { properties: { block_id: string; highlight: number } }[];
      };
      const b1 = blocks.features.find((f) => f.properties.block_id === "b1");
      expect(b1?.properties.highlight).toBe(1);
    });
  });

  it("says the picture is older than the date being read", async () => {
    await renderAtFixtureWindow();
    // The only pass in the fixture is 2 June, so every later frame is
    // carrying it forward. Saying so is what stops a reader taking it for
    // an image of the day on the scrubber.
    seekTo("2026-06-09");
    expect(await screen.findByText(/Image from/)).toBeInTheDocument();
  });

  it("says a frame before the first pass has no picture at all", async () => {
    await renderAtFixtureWindow();
    seekTo("2026-06-01");
    expect(await screen.findByText(/No image yet/)).toBeInTheDocument();
  });

  it("names the kinds this reader cannot see instead of hiding them", async () => {
    await renderAtFixtureWindow();
    seekTo("2026-06-03");
    const omitted = await screen.findByText(/your role cannot read them/i);
    expect(within(omitted).getByText(/Recommendation/i)).toBeDefined();
  });
});

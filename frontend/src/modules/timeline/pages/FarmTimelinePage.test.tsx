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
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { listFarmSceneAssets } from "@/api/imagery";
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

/** Acquisition days in the fixture window, oldest first. */
const SCENE_DAYS = vi.hoisted(() => [
  "2026-06-02",
  "2026-06-03",
  "2026-06-04",
  "2026-06-05",
  "2026-06-06",
  "2026-06-07",
]);

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
    median_gap_days: 2,
    // Six passes, deliberately more than the map preloads at once. Four
    // are enough to prove the preload window; the two past it are what
    // give the prepare step real work to do, and a fixture with one pass
    // cannot tell a warm cache from a prepare that never ran.
    items: SCENE_DAYS.map((day) => ({
      scene_date: day,
      at: `${day}T08:30:00Z`,
      block_count: 1,
      succeeded_count: 1,
      skipped_cloud_count: 0,
      computed_count: 1,
      cloud_cover_pct: "1.0",
    })),
  })),
  // Answers for the pass it was ASKED for. A stub that returned one fixed
  // date whatever `at` said would hide the bug this fixture exists to
  // catch: a preloaded pass judged against the current frame's date
  // instead of its own fails `farmRasterForPass` and falls back to the
  // per-block path, which looks identical on the active frame.
  listFarmSceneAssets: vi.fn(async (_farmId: string, at?: string) => ({
    farm_id: "f1",
    at: at ?? null,
    farm: at
      ? {
          stac_item_id: `sentinel_hub/s2l2a/${at.slice(0, 10)}/aoihash`,
          scene_datetime: at,
          resolution_m: "10",
          blocks_merged: null,
          source: "fetched" as const,
        }
      : null,
    items: [
      {
        block_id: "b1",
        product_id: "prod",
        stac_item_id: "sentinel_hub/s2l2a/SCENE/aoihash",
        scene_datetime: at ?? "2026-06-02T08:30:00Z",
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

/** The map's own date caption, which is not the rail's heading. */
function imageDate(): Promise<HTMLElement> {
  return screen.findByTestId("timeline-image-date");
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

  it("captions the map with the day the picture was taken, not the day being read", async () => {
    await renderAtFixtureWindow();
    // The last pass in the fixture is 7 June, so 9 June is carrying it
    // forward. The caption is what stops a reader taking it for an image
    // of the day on the scrubber.
    seekTo("2026-06-09");
    expect(await imageDate()).toHaveTextContent("Jun 7, 2026");
  });

  it("keeps the caption on screen on the day the picture was actually taken", async () => {
    await renderAtFixtureWindow();
    // The regression this pins: the old header badge only appeared when
    // the pass was OLDER than the frame, so on an acquisition day — the
    // one a reader most wants confirmed — the caption blinked out. At
    // playback speed that is a flicker every five frames.
    seekTo("2026-06-07");
    expect(await imageDate()).toHaveTextContent("Jun 7, 2026");

    // And it does not change on a carried-forward day, because the
    // picture has not changed. That is the whole signal the caption
    // carries: when this number does not move, neither did the image.
    seekTo("2026-06-08");
    await waitFor(() =>
      expect(screen.getByTestId("timeline-image-date")).toHaveTextContent("Jun 7, 2026"),
    );
  });

  it("hides a datapoint kind from BOTH the map and the rail when its box is off", async () => {
    await renderAtFixtureWindow();
    seekTo("2026-06-03");
    expect(await screen.findByText("NDVI fell 22% in seven days")).toBeInTheDocument();
    await waitFor(() => {
      const marks = mapProps.current?.marks as { features: unknown[] };
      expect(marks.features).toHaveLength(1);
    });

    fireEvent.click(screen.getByRole("checkbox", { name: "Alert" }));

    // One switch, both halves. The replay's rule is that the map and the
    // rail read the same frame, so a kind that is off must be off in both
    // — a rail listing an alert the map does not draw is the disagreement
    // the whole screen is built to avoid.
    await waitFor(() => {
      const marks = mapProps.current?.marks as { features: unknown[] };
      expect(marks.features).toHaveLength(0);
    });
    expect(screen.queryByText("NDVI fell 22% in seven days")).not.toBeInTheDocument();
  });

  it("leaves the scrubber's ticks alone when a kind is switched off", async () => {
    await renderAtFixtureWindow();
    fireEvent.click(screen.getByRole("checkbox", { name: "Alert" }));

    // Deliberate. The ticks say WHERE in the window something happened,
    // and a reader who has hidden alerts still needs to find the day one
    // was raised in order to switch them back on.
    seekTo("2026-06-03");
    expect(await screen.findByText("1 datapoint")).toBeInTheDocument();
  });

  it("stops drawing pixels without discarding them when the box is off", async () => {
    await renderAtFixtureWindow();
    seekTo("2026-06-03");
    await waitFor(() => expect(mapProps.current?.activeRasterKey).toBeTruthy());
    const frames = mapProps.current?.rasterFrames as unknown[];

    fireEvent.click(screen.getByRole("checkbox", { name: "Index pixels" }));

    await waitFor(() => {
      // The frames stay on the map; only the active key goes. Dropping
      // them would make switching pixels back on a re-fetch of every tile
      // the reader has already paid for.
      expect(mapProps.current?.showPixels).toBe(false);
      expect(mapProps.current?.rasterFrames).toHaveLength(frames.length);
    });
  });

  it("holds the next passes on the map, each judged against its own date", async () => {
    await renderAtFixtureWindow();
    seekTo("2026-06-02");

    await waitFor(() => {
      const frames = mapProps.current?.rasterFrames as {
        key: string;
        layers: { id: string; tileUrl: string }[];
      }[];
      // The current pass and three ahead of it. Bounded: the window has
      // six passes and the map must not end up holding all of them, nor
      // 36 block sources apiece on a per-block farm.
      expect(frames).toHaveLength(4);

      frames.forEach((f, n) => {
        const day = SCENE_DAYS[n];
        // One farm surface per pass, not a fallback to the per-block path.
        // `farmRasterForPass` returns the surface only when its UTC day
        // equals the day of the `at` it is given, so judging a preloaded
        // pass against the CURRENT frame's date returns null for every one
        // of them and quietly drops the replay onto per-block rasters —
        // invisible on screen, because the active frame is still right.
        expect(f.layers).toHaveLength(1);
        expect(f.layers[0].id).toBe("__farm__");
        expect(f.layers[0].tileUrl).toContain(day);
        expect(f.key).toContain(day);
      });

      // And exactly one of them is painted.
      expect(mapProps.current?.activeRasterKey).toBe(frames[0].key);
    });
  });

  it("loads the window's passes before it starts playing", async () => {
    const assets = vi.mocked(listFarmSceneAssets);
    await renderAtFixtureWindow();
    await waitFor(() => expect(assets).toHaveBeenCalled());

    // Hold the prepare open so the state it puts the button in can be
    // read. Without this the fixture's single pass resolves from cache
    // within one tick and the step is invisible to the test — which is
    // also why it was worth naming on the button in the first place.
    let release = (): void => {};
    assets.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          release = () => resolve(null);
        }),
    );

    fireEvent.click(screen.getByRole("button", { name: "Play" }));
    expect(await screen.findByRole("button", { name: "Preparing…" })).toBeInTheDocument();
    // Not running yet. Starting against an empty cache is what made the
    // map trail the scrubber by seconds.
    expect(scrubber().value).toBe("9");

    release();
    await waitFor(() => expect(screen.getByRole("button", { name: "Pause" })).toBeInTheDocument());
  });

  it("a second press during the prepare cancels it rather than queueing a run", async () => {
    const assets = vi.mocked(listFarmSceneAssets);
    await renderAtFixtureWindow();
    await waitFor(() => expect(assets).toHaveBeenCalled());

    let release = (): void => {};
    assets.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          release = () => resolve(null);
        }),
    );

    fireEvent.click(screen.getByRole("button", { name: "Play" }));
    await screen.findByRole("button", { name: "Preparing…" });
    fireEvent.click(screen.getByRole("button", { name: "Preparing…" }));

    expect(await screen.findByRole("button", { name: "Play" })).toBeInTheDocument();
    release();
    // The abandoned prepare must not start the replay behind the reader's
    // back once its requests land.
    await waitFor(() => expect(screen.getByRole("button", { name: "Play" })).toBeInTheDocument());
  });

  it("says a frame before the first pass has no picture at all", async () => {
    await renderAtFixtureWindow();
    seekTo("2026-06-01");
    expect(await imageDate()).toHaveTextContent("No image yet");
  });

  it("names the kinds this reader cannot see instead of hiding them", async () => {
    await renderAtFixtureWindow();
    seekTo("2026-06-03");
    const omitted = await screen.findByText(/your role cannot read them/i);
    expect(within(omitted).getByText(/Recommendation/i)).toBeDefined();
  });
});

import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { FarmScene } from "@/api/imagery";
import { setupTestI18n } from "@/i18n/testing";
import { SceneTimeline } from "./SceneTimeline";

/**
 * A pass can succeed and still leave holes in the map.
 *
 * The scene-classification mask drops cloud, shadow and cirrus pixels. Green
 * Farm [Demo-01] on 2026-08-18 is the worked example: the job succeeded, 319
 * of the farm's 5,037 pixels were flagged cloud, and 84 of AG-R02-C02's 224
 * grid cells came back with no value. The strip showed a plain "4", so the
 * missing colour read as a fault in the map.
 *
 * The measurement is `no_reading_pct` and NOT `cloud_cover_pct`. The second is
 * the whole satellite tile's figure and ranks these two days backwards: it
 * calls 08-17 the cloudier day at 13.24% against 08-18's 6.50%, while the farm
 * lost 2.04% on 08-17 and 8.17% on 08-18.
 */
function scene(over: Partial<FarmScene>): FarmScene {
  return {
    scene_date: "2026-08-15",
    at: "2026-08-15T08:41:53Z",
    block_count: 4,
    succeeded_count: 4,
    skipped_cloud_count: 0,
    computed_count: 4,
    cloud_cover_pct: "0.07",
    no_reading_pct: "2.04",
    ...over,
  };
}

/** The 2026-08-18 pass, next to a clear day so the floor is 2%. */
const CLOUDY_DAY = scene({
  scene_date: "2026-08-18",
  at: "2026-08-18T08:51:49Z",
  cloud_cover_pct: "6.50",
  no_reading_pct: "8.17",
});

function renderStrip(scenes: FarmScene[]) {
  render(
    <SceneTimeline
      scenes={scenes}
      selectedDate={null}
      onSelect={vi.fn()}
      medianGapDays={5}
      loading={false}
      available
    />,
  );
}

describe("SceneTimeline — a pass that succeeded under partial cloud", () => {
  beforeEach(async () => {
    await setupTestI18n();
  });

  it("shows what the pass cost the farm", () => {
    renderStrip([scene({}), CLOUDY_DAY]);
    expect(screen.getByText("☁ 8%")).toBeInTheDocument();
  });

  it("keeps that pass selectable and says what the loss means", () => {
    renderStrip([scene({}), CLOUDY_DAY]);
    // The strip renders oldest first, so pick the chip by its own label
    // rather than by position.
    const btn = screen.getByText("☁ 8%").closest("button");
    expect(btn).not.toBeDisabled();
    expect(btn?.getAttribute("title")).toMatch(/8% of the farm has no reading/);
  });

  it("ignores the tile cloud figure, which ranks the days backwards", () => {
    // 08-17 carries the higher tile cloud (13.24%) and the lower farm loss
    // (2.04%). Reading the tile figure would flag the wrong day.
    renderStrip([
      scene({ scene_date: "2026-08-17", cloud_cover_pct: "13.24", no_reading_pct: "2.04" }),
      CLOUDY_DAY,
    ]);
    expect(screen.queryByText("☁ 13%")).not.toBeInTheDocument();
    expect(screen.getByText("☁ 8%")).toBeInTheDocument();
  });

  it("treats the farm's own quiet pass as the floor, not zero", () => {
    // Every farm loses its boundary pixels on every pass. A strip of clear
    // days at a steady 2.04% must stay silent.
    renderStrip([scene({ scene_date: "2026-08-13" }), scene({ scene_date: "2026-08-15" })]);
    expect(screen.getAllByText("4")).toHaveLength(2);
    expect(screen.queryByText(/☁/)).not.toBeInTheDocument();
  });

  it("flags a large loss even when every pass on the strip is cloudy", () => {
    // No quiet pass to measure against, so the floor is high and the relative
    // rule finds nothing. An absolute rule still has to fire.
    renderStrip([
      scene({ scene_date: "2026-08-13", no_reading_pct: "31.00" }),
      scene({ scene_date: "2026-08-15", no_reading_pct: "33.00" }),
    ]);
    expect(screen.getByText("☁ 31%")).toBeInTheDocument();
    expect(screen.getByText("☁ 33%")).toBeInTheDocument();
  });

  it("stays on the block count on an api that predates the field", () => {
    renderStrip([scene({ no_reading_pct: null }), scene({ scene_date: "2026-08-18" })]);
    expect(screen.queryByText(/☁/)).not.toBeInTheDocument();
  });

  it("keeps the strike-through for a pass skipped entirely for cloud", () => {
    renderStrip([
      scene({
        succeeded_count: 0,
        skipped_cloud_count: 4,
        computed_count: 0,
        cloud_cover_pct: "91.00",
        no_reading_pct: null,
      }),
    ]);
    expect(screen.getByText("☁ 91%")).toBeInTheDocument();
    expect(screen.getByRole("option").getAttribute("title")).toMatch(/skipped/i);
  });

  it("leaves an unprocessed pass disabled rather than calling it cloudy", () => {
    // Nothing was computed, so there is nothing to draw at all. That is the
    // stronger statement and it keeps its own treatment.
    renderStrip([scene({ computed_count: 0, no_reading_pct: null })]);
    const btn = screen.getByRole("option");
    expect(btn).toBeDisabled();
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});

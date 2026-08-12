import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { FarmScene } from "@/api/imagery";
import { setupTestI18n } from "@/i18n/testing";
import { SceneTimeline } from "./SceneTimeline";

/**
 * A pass can be fully ingested and still be undrawable.
 *
 * Ingestion and index computation are separate tasks, and a historical
 * backfill runs only the first — on the reference farm that left 104 of 131
 * days with imagery fetched and no index raster ever written. The strip used
 * to offer every one of them, and picking one painted nothing.
 */
function scene(over: Partial<FarmScene>): FarmScene {
  return {
    scene_date: "2026-07-01",
    at: "2026-07-01T08:30:00Z",
    block_count: 4,
    succeeded_count: 4,
    skipped_cloud_count: 0,
    computed_count: 4,
    cloud_cover_pct: "3.00",
    ...over,
  };
}

function renderStrip(scenes: FarmScene[], onSelect = vi.fn()) {
  render(
    <SceneTimeline
      scenes={scenes}
      selectedDate={null}
      onSelect={onSelect}
      medianGapDays={5}
      loading={false}
      available
    />,
  );
  return onSelect;
}

describe("SceneTimeline — passes that were never processed", () => {
  beforeEach(async () => {
    await setupTestI18n();
  });

  it("disables a pass whose indices were never computed", () => {
    renderStrip([scene({ scene_date: "2025-06-16", computed_count: 0 })]);
    const btn = screen.getByRole("option");
    expect(btn).toBeDisabled();
    expect(btn.getAttribute("title")).toMatch(/never processed/i);
  });

  it("keeps a processed pass selectable", () => {
    const onSelect = renderStrip([scene({})]);
    const btn = screen.getByRole("option");
    expect(btn).not.toBeDisabled();
    btn.click();
    expect(onSelect).toHaveBeenCalledWith("2026-07-01");
  });

  it("lets cloud keep its own explanation", () => {
    // A cloud-skipped day also computes nothing, but "☁ 91%" says both that
    // there is nothing to draw AND why. A grey dash would lose the why.
    renderStrip([
      scene({ succeeded_count: 0, skipped_cloud_count: 4, computed_count: 0, cloud_cover_pct: "91.00" }),
    ]);
    expect(screen.getByText("☁ 91%")).toBeInTheDocument();
  });
});

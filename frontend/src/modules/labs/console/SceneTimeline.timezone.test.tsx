import { render, screen } from "@testing-library/react";
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import type { FarmScene } from "@/api/imagery";
import { setupTestI18n } from "@/i18n/testing";
import { SceneTimeline } from "./SceneTimeline";

/**
 * An acquisition day is a DATE, not an instant.
 *
 * `scene_date` comes off the api as `(scene_datetime AT TIME ZONE 'UTC')
 * ::date`, and the strip used to render it through the viewer's own clock.
 * West of Greenwich that reads midnight UTC as the evening before, so every
 * label on the strip slid back a day — a user on a negative-offset clock read
 * the 15 Aug pass as "14 Aug" and reasonably concluded the console was
 * serving the wrong scene.
 *
 * The date the api grouped by is the date the user has to see, or the two
 * ends of the same screen are talking about different days.
 */
const ORIGINAL_TZ = process.env.TZ;

function scene(over: Partial<FarmScene>): FarmScene {
  return {
    scene_date: "2026-08-15",
    at: "2026-08-15T08:41:47Z",
    block_count: 36,
    succeeded_count: 36,
    skipped_cloud_count: 0,
    computed_count: 36,
    cloud_cover_pct: "3.00",
    ...over,
  };
}

describe("SceneTimeline — the acquisition day survives the viewer's clock", () => {
  beforeAll(() => {
    // Ten hours behind UTC: midnight UTC is 2pm the previous day here.
    process.env.TZ = "Pacific/Honolulu";
  });
  afterAll(() => {
    process.env.TZ = ORIGINAL_TZ;
  });
  beforeEach(async () => {
    await setupTestI18n();
  });

  it("labels a pass with its own date, not the viewer's yesterday", () => {
    render(
      <SceneTimeline
        scenes={[scene({})]}
        selectedDate={null}
        onSelect={vi.fn()}
        medianGapDays={5}
        loading={false}
        available
      />,
    );

    // Sanity: this environment really is shifted, so the assertion below is
    // testing the fix rather than an accident of where CI happens to run.
    expect(
      new Intl.DateTimeFormat("en", { day: "2-digit", month: "short" }).format(
        new Date("2026-08-15T00:00:00Z"),
      ),
    ).toBe("Aug 14");

    expect(screen.getByRole("option")).toHaveTextContent(/15/);
    expect(screen.getByRole("option")).not.toHaveTextContent(/14/);
  });

  it("says the same day in the tooltip as on the chip", () => {
    render(
      <SceneTimeline
        scenes={[scene({})]}
        selectedDate={null}
        onSelect={vi.fn()}
        medianGapDays={5}
        loading={false}
        available
      />,
    );

    // The tooltip is the long form of the same value; a strip that disagreed
    // with its own tooltip would be worse than one that is simply a day out.
    expect(screen.getByRole("option").getAttribute("title")).toMatch(/15/);
  });
});

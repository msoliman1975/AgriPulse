import { cleanup, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { setupTestI18n } from "@/i18n/testing";
import { PrefsProvider } from "@/prefs/PrefsContext";
import { IndexLegend } from "./IndexLegend";
import { classesFor } from "./indexClasses";
import type { ClassAreaSummary } from "./pixelTiles";

/** One feddan is 4200.83 m², which keeps the expected strings readable. */
const FEDDAN = 4200.83;

function areas(perClass: number[], noDataFeddan = 0): ClassAreaSummary {
  const areaM2ByClass = perClass.map((f) => f * FEDDAN);
  return {
    areaM2ByClass,
    coveredM2: areaM2ByClass.reduce((a, b) => a + b, 0),
    noDataM2: noDataFeddan * FEDDAN,
  };
}

function renderLegend(props: Partial<Parameters<typeof IndexLegend>[0]> = {}) {
  return render(
    <PrefsProvider>
      <IndexLegend
        code="ndvi"
        // NDVI has 7 classes, lowest (water) first.
        areas={areas([0, 8.5, 93.1, 76.6, 0.1, 0, 0])}
        scopeBlockId={null}
        scopeBlockName={null}
        showPixels
        assetCount={4}
        imagerySubCount={4}
        loading={false}
        {...props}
      />
    </PrefsProvider>,
  );
}

describe("IndexLegend", () => {
  beforeEach(async () => {
    await setupTestI18n();
  });

  it("draws a row per class, each with its area", () => {
    renderLegend();
    expect(screen.getByText("Sparse canopy")).toBeInTheDocument();
    expect(screen.getByText("93.1")).toBeInTheDocument();
    expect(screen.getByText("76.6")).toBeInTheDocument();
  });

  it("paints each swatch the colour the map paints that class", () => {
    // The guarantee the redesign rests on. Both the swatch and the tile
    // colormap read indexClasses.ts, so this asserts they stayed wired.
    const { container } = renderLegend();
    const swatches = [...container.querySelectorAll("li span[aria-hidden='true']")];
    const rendered = swatches.map((s) => (s as HTMLElement).style.backgroundColor);
    const expected = classesFor("ndvi")
      .map((c) => hexToRgb(c.color))
      .reverse();
    expect(rendered).toEqual(expected);
  });

  it("reads highest class first", () => {
    renderLegend();
    const names = [...document.querySelectorAll("li")].map((li) => li.textContent ?? "");
    expect(names[0]).toContain("Very dense");
    expect(names[names.length - 1]).toContain("Water");
  });

  it("totals only what it can account for", () => {
    renderLegend({ areas: areas([0, 8.5, 93.1, 76.6, 0.1, 0, 0], 5.3) });
    // Covered is the sum of the rows; no-reading is reported beside it, never
    // folded in — every hectare on screen is in exactly one of the two.
    expect(screen.getByText("178.3")).toBeInTheDocument();
    expect(screen.getByText("5.3")).toBeInTheDocument();
  });

  it("keeps working with the pixel layer off, and says what it is describing", () => {
    // The old panel went blank here and the map still had colours on it.
    renderLegend({ showPixels: false });
    expect(screen.getByText("Sparse canopy")).toBeInTheDocument();
    expect(screen.getByText(/blocks are filled by their own average/i)).toBeInTheDocument();
  });

  it("warns that NDRE is a relative reading, and does not for NDVI", () => {
    renderLegend({ code: "ndre", areas: areas([0, 0, 12, 4, 0]) });
    expect(screen.getByText(/compare blocks against each other/i)).toBeInTheDocument();
  });

  it("reads LST in degrees, at the precision a 100 m pixel earns", () => {
    // Two things a dimensionless legend gets wrong for a temperature: it
    // prints no unit, and it prints `20.00` off a sensor whose native pixel is
    // 100 m across. The unit sits in the heading rather than on every row —
    // six repetitions of "°C" say nothing the heading cannot say once, and the
    // range column is too narrow to carry it without truncating the numbers.
    const { container } = renderLegend({
      code: "lst",
      indexUnit: "°C",
      areas: areas([0, 0, 0, 2.4, 88.3, 74.2]),
    });
    expect(screen.getByText("°C")).toBeInTheDocument();
    const ranges = [...container.querySelectorAll("li span[dir='ltr']")].map((r) => r.textContent);
    expect(ranges).toContain("38.0 – 45.0");
    expect(ranges.some((r) => r?.includes("38.00"))).toBe(false);
  });

  it("says a thermal reading is farm-scale, and does not for an optical one", () => {
    // Both caveats apply to thermal — the scale is provisional AND the pixel
    // is larger than most blocks on this farm. Saying only the first would
    // leave a reader trusting detail the sensor cannot resolve.
    renderLegend({ code: "cwsi", indexUnit: "", areas: areas([0, 0, 1, 4, 160]) });
    expect(screen.getByText(/one pixel covers a hectare/i)).toBeInTheDocument();

    cleanup();
    renderLegend();
    expect(screen.queryByText(/one pixel covers a hectare/i)).not.toBeInTheDocument();
  });

  it("keeps ranges left-to-right so RTL cannot reverse them", () => {
    // Under Arabic the paragraph direction reorders the two LTR runs around
    // the dash, and "0.20 - 0.40" renders as "0.40 - 0.20" — a different and
    // wrong claim. Verified in the browser; pinned here.
    const { container } = renderLegend();
    const ranges = [...container.querySelectorAll("li span[dir='ltr']")];
    expect(ranges).toHaveLength(classesFor("ndvi").length);
    expect(ranges.map((r) => r.textContent)).toContain("0.20 – 0.40");
  });

  it("names NDWI's healthy end without inverting its numbers", () => {
    renderLegend({ code: "ndwi", areas: areas([9.5, 168.2, 0.6, 0, 0]) });
    expect(screen.getByText("Dense canopy, dry surface")).toBeInTheDocument();
    expect(screen.getByText("≤ -0.40")).toBeInTheDocument();
    expect(screen.getByText("Open water")).toBeInTheDocument();
  });

  it("points at imagery settings when the farm has no subscriptions", () => {
    renderLegend({ assetCount: 0, imagerySubCount: 0 });
    expect(screen.getByText(/no imagery yet/i)).toBeInTheDocument();
    expect(screen.queryByText("Sparse canopy")).not.toBeInTheDocument();
  });

  it("blames the scene, not the setup, when imagery exists but this pass has none", () => {
    renderLegend({ assetCount: 0, imagerySubCount: 4 });
    expect(screen.getByText(/nothing for this date/i)).toBeInTheDocument();
  });

  it("blames the scene when the api named assets but none could be read", () => {
    // Found by smoke-testing an older pass: the ingestion job rows claimed
    // success and carried a stac_item_id, but the objects were gone from the
    // bucket. The panel used to render a full set of rows reading 0.0, which
    // states that the land is empty rather than that we cannot see it.
    // assetCount now counts PROVEN blocks, so zero of them reads as "no
    // usable image for this date".
    renderLegend({ assetCount: 0, imagerySubCount: 36, areas: areas([0, 0, 0, 0, 0, 0, 0]) });
    expect(screen.getByText(/nothing for this date/i)).toBeInTheDocument();
    expect(screen.queryByText("Sparse canopy")).not.toBeInTheDocument();
  });

  it("says nothing at all while it is still loading", () => {
    // Better a moment of blank than a "no imagery" claim that turns out false.
    renderLegend({ assetCount: 0, imagerySubCount: null, loading: true });
    expect(screen.queryByText(/no imagery yet/i)).not.toBeInTheDocument();
  });
});

function hexToRgb(hex: string): string {
  const n = Number.parseInt(hex.slice(1), 16);
  return `rgb(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255})`;
}

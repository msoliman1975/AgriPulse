import { fireEvent, render, screen } from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { Map as MapLibreMap } from "maplibre-gl";

import { setupTestI18n } from "@/i18n/testing";

import { SatelliteBasemapControl } from "./SatelliteBasemapControl";

const apply = vi.fn();
vi.mock("./latestPhoto", () => ({
  applyLatestPhoto: (...args: unknown[]) => apply(...args),
}));
let baseDate: string | null = "2020-04-19";
vi.mock("./useBasemap", () => ({ useBaseCaptureDate: () => baseDate }));

const map = {} as MapLibreMap;
const photo = { scene_datetime: "2026-11-08T08:39:21Z", tile_url: "https://tiles/x" };

function renderControl(p: typeof photo | null = photo) {
  return render(<SatelliteBasemapControl map={map} photo={p} />);
}

describe("SatelliteBasemapControl", () => {
  beforeAll(async () => {
    await setupTestI18n("en");
  });
  beforeEach(() => {
    apply.mockClear();
    baseDate = "2020-04-19";
    window.localStorage.clear();
  });

  it("shows the sharp base by default and says a newer photo exists", () => {
    renderControl();
    expect(apply).toHaveBeenLastCalledWith(map, "https://tiles/x", false, null);
    expect(screen.getByRole("radio", { name: "Sharp (older)" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.getByText("Satellite image of Apr 19, 2020")).toBeInTheDocument();
    expect(screen.getByText(/Newer photo: Sentinel-2, Nov 8, 2026/)).toBeInTheDocument();
  });

  it("lays the latest photo on when picked, dates both images, and remembers it", () => {
    renderControl();
    fireEvent.click(screen.getByRole("radio", { name: "Latest (10 m)" }));
    expect(apply).toHaveBeenLastCalledWith(map, "https://tiles/x", true, null);
    expect(screen.getByText(/Sentinel-2 photo of Nov 8, 2026/)).toBeInTheDocument();
    expect(screen.getByText(/high-res image of Apr 19, 2020/)).toBeInTheDocument();
    expect(window.localStorage.getItem("agripulse.basemap.v2")).toBe("latest");
  });

  it("without a photo still says how old the base is, with no switch", () => {
    renderControl(null);
    expect(screen.queryByRole("radiogroup")).toBeNull();
    expect(screen.getByText("Satellite image of Apr 19, 2020")).toBeInTheDocument();
    expect(apply).toHaveBeenLastCalledWith(map, null, false, null);
  });

  it("renders nothing when there is neither a photo nor a date", () => {
    baseDate = null;
    const { container } = renderControl(null);
    expect(container).toBeEmptyDOMElement();
  });
});

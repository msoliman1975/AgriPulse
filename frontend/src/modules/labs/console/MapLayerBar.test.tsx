// The top-bar layer controls.
//
// These were checkboxes buried in a popover; the point of moving them is that
// they are now visible and directly clickable, so the tests reach for them by
// their accessible role rather than by opening anything.
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";
import type { LayerState } from "../mapnext/ViewBar";
import { MapLayerBar } from "./MapLayerBar";

const LAYERS: LayerState = {
  aoi: true,
  blocks: true,
  borders: true,
  labels: true,
  borderOpacity: 0.6,
  flags: true,
  flagsOpenOnly: true,
  signals: true,
  labelField: "name",
  alerts: true,
  markLegend: false,
};

function renderBar(
  layers: Partial<LayerState> = {},
  props: Partial<Parameters<typeof MapLayerBar>[0]> = {},
) {
  const onLayersChange = vi.fn();
  const onToggleGrid = vi.fn();
  render(
    <MapLayerBar
      layers={{ ...LAYERS, ...layers }}
      onLayersChange={onLayersChange}
      showGrid
      onToggleGrid={onToggleGrid}
      gridAvailable
      {...props}
    />,
  );
  return { onLayersChange, onToggleGrid };
}

describe("MapLayerBar", () => {
  beforeEach(async () => {
    await setupTestI18n();
  });

  afterEach(cleanup);

  it("shows the three layer checkboxes without opening anything", () => {
    renderBar();
    expect(screen.getByRole("checkbox", { name: /Farm borders/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /Block\/pivot borders/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /Cells/ })).toBeChecked();
  });

  it("reports a border toggle as a layer patch", async () => {
    const user = userEvent.setup();
    const { onLayersChange } = renderBar();
    await user.click(screen.getByRole("checkbox", { name: /Farm borders/ }));
    expect(onLayersChange).toHaveBeenCalledWith({ aoi: false });
  });

  it("routes Cells to the grid toggle, not to the layer patch", async () => {
    // The mesh is its own piece of state — it drives a query, not a paint
    // property — so it must not be folded into LayerState by accident.
    const user = userEvent.setup();
    const { onToggleGrid, onLayersChange } = renderBar();
    await user.click(screen.getByRole("checkbox", { name: /Cells/ }));
    expect(onToggleGrid).toHaveBeenCalled();
    expect(onLayersChange).not.toHaveBeenCalled();
  });

  it("disables Cells when the farm has no zoning, and says so on the bar", () => {
    // The one reason it can be disabled. A tooltip on a disabled checkbox is
    // not an explanation, so the reason is printed next to it.
    renderBar({}, { gridAvailable: false });
    expect(screen.getByRole("checkbox", { name: /Cells/ })).toBeDisabled();
    expect(screen.getByText(/no cells configured/i)).toBeInTheDocument();
  });

  it("keeps Cells usable whatever the map is drawing", () => {
    // The mesh is geometry. It used to grey out on a thermal index and on
    // "None", which made a farm's zoning look absent because of what was
    // being painted over it.
    renderBar();
    const cells = screen.getByRole("checkbox", { name: /Cells/ });
    expect(cells).toBeEnabled();
    expect(cells).toBeChecked();
    expect(screen.queryByText(/no cells configured/i)).toBeNull();
  });

  it("carries the border opacity slider, labelled with its percentage", () => {
    renderBar({ borderOpacity: 0.6 });
    expect(screen.getByRole("slider", { name: /Border opacity — 60%/ })).toBeInTheDocument();
  });

  // Blocks draw no fill any more, so the slider that set its opacity is
  // gone. It was the one control on this bar that could make the map look
  // broken — a reader who dragged it to 0 saw the health colours vanish.
  it("has no block fill opacity slider", () => {
    renderBar();
    expect(screen.queryByRole("slider", { name: /fill/i })).toBeNull();
  });

  it("reports an opacity change as a 0..1 fraction", () => {
    // The bar renders whole percent; the map wants 0..1. Getting that
    // conversion backwards paints every border at 1% and reads as "the
    // borders disappeared".
    const { onLayersChange } = renderBar();
    fireEvent.change(screen.getByRole("slider", { name: /Border opacity/ }), {
      target: { value: "35" },
    });
    expect(onLayersChange).toHaveBeenCalledWith({ borderOpacity: 0.35 });
  });

  it("offers the label field only while labels are on", () => {
    renderBar({ labels: false });
    expect(screen.queryByRole("button", { name: "Crop" })).toBeNull();
  });

  it("switches the label to the crop", async () => {
    const user = userEvent.setup();
    const { onLayersChange } = renderBar({ labels: true, labelField: "name" });
    await user.click(screen.getByRole("button", { name: "Crop" }));
    expect(onLayersChange).toHaveBeenCalledWith({ labelField: "crop" });
  });

  it("marks the active label field as pressed", () => {
    renderBar({ labelField: "crop" });
    expect(screen.getByRole("button", { name: "Crop" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Block name" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });
});

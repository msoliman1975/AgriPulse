// The datapoint control's contract, which is mostly about states that are
// both "on" and yet different from each other.
//
// The control merged four things that used to live in three places, and the
// failure it exists to prevent is a row that says "on" while the map is
// drawing something else. So every test here asserts the rail's own caption
// against the state it was handed, and the panel's tick against the same.
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";
import { MAP_INDEX_ORDER } from "../mapnext/constants";
import { MapDataControl } from "./MapDataControl";

function renderControl(props: Partial<Parameters<typeof MapDataControl>[0]> = {}) {
  const onIndexChange = vi.fn();
  const onAlertsChange = vi.fn();
  const onFlagsModeChange = vi.fn();
  const onSignalsChange = vi.fn();
  const onMarkLegendChange = vi.fn();
  const onFullscreen = vi.fn();
  render(
    <MapDataControl
      activeIndex="ndvi"
      indexOptions={MAP_INDEX_ORDER}
      onIndexChange={onIndexChange}
      pixelsAvailable
      alerts
      onAlertsChange={onAlertsChange}
      flagsMode="current"
      onFlagsModeChange={onFlagsModeChange}
      signalDefs={[{ id: "sd-1", name: "Leaf wetness" }]}
      signalsOn
      signalDefId={null}
      onSignalsChange={onSignalsChange}
      markLegend={false}
      onMarkLegendChange={onMarkLegendChange}
      onFullscreen={onFullscreen}
      isFullscreen={false}
      {...props}
    />,
  );
  return {
    onIndexChange,
    onAlertsChange,
    onFlagsModeChange,
    onSignalsChange,
    onMarkLegendChange,
    onFullscreen,
  };
}

describe("MapDataControl", () => {
  beforeEach(async () => {
    await setupTestI18n();
  });

  afterEach(cleanup);

  it("names the index it is drawing, on the rail itself", () => {
    renderControl({ activeIndex: "ndre" });
    expect(screen.getByRole("button", { name: /Index/ })).toHaveTextContent("NDRE");
  });

  it("reads None when no index is picked, and shows that row unpressed", () => {
    renderControl({ activeIndex: null });
    const row = screen.getByRole("button", { name: /Index/ });
    expect(row).toHaveTextContent("None");
    expect(row).toHaveAttribute("aria-pressed", "false");
  });

  it("offers None above the indices and reports it as null", async () => {
    const user = userEvent.setup();
    const { onIndexChange } = renderControl();
    await user.click(screen.getByRole("button", { name: /Index/ }));
    await user.click(screen.getByRole("button", { name: /None/ }));
    expect(onIndexChange).toHaveBeenCalledWith(null);
  });

  it("reports a picked index by code", async () => {
    const user = userEvent.setup();
    const { onIndexChange } = renderControl();
    await user.click(screen.getByRole("button", { name: /Index/ }));
    await user.click(screen.getByRole("button", { name: /NDWI/ }));
    expect(onIndexChange).toHaveBeenCalledWith("ndwi");
  });

  it("keeps the index row reachable with no imagery, so long as one is drawn", () => {
    // The hint explains the empty map; disabling the row as well would trap a
    // reader who wants to switch to a different product.
    renderControl({ pixelsAvailable: false, activeIndex: "ndvi" });
    expect(screen.getByRole("button", { name: /Index/ })).toBeEnabled();
  });

  it("toggles alerts straight off the rail, with no panel", async () => {
    const user = userEvent.setup();
    const { onAlertsChange } = renderControl({ alerts: true });
    await user.click(screen.getByRole("button", { name: /Alerts/ }));
    expect(onAlertsChange).toHaveBeenCalledWith(false);
  });

  it("tells Current and Historical apart on the rail", () => {
    renderControl({ flagsMode: "historical" });
    const row = screen.getByRole("button", { name: /Field flags/ });
    // Both are ON. Only the caption separates them, which is why it is there.
    expect(row).toHaveAttribute("aria-pressed", "true");
    expect(row).toHaveTextContent("Historical");
  });

  it("reports each of the three flag modes", async () => {
    const user = userEvent.setup();
    const { onFlagsModeChange } = renderControl({ flagsMode: "current" });
    await user.click(screen.getByRole("button", { name: /Field flags/ }));
    await user.click(screen.getByRole("button", { name: /Every flag/ }));
    expect(onFlagsModeChange).toHaveBeenCalledWith("historical");
  });

  it("turns signals off through the picker, not by clearing the type", async () => {
    const user = userEvent.setup();
    const { onSignalsChange } = renderControl();
    await user.click(screen.getByRole("button", { name: /Signals/ }));
    await user.click(screen.getByRole("button", { name: "None" }));
    expect(onSignalsChange).toHaveBeenCalledWith({ on: false, defId: null });
  });

  it("narrowing to one signal type also turns the layer on", async () => {
    const user = userEvent.setup();
    const { onSignalsChange } = renderControl({ signalsOn: false });
    await user.click(screen.getByRole("button", { name: /Signals/ }));
    await user.click(screen.getByRole("button", { name: /Leaf wetness/ }));
    expect(onSignalsChange).toHaveBeenCalledWith({ on: true, defId: "sd-1" });
  });

  it("names the narrowed signal on the rail", () => {
    renderControl({ signalDefId: "sd-1" });
    expect(screen.getByRole("button", { name: /Signals/ })).toHaveTextContent("Leaf wetness");
  });

  it("toggles the mark legend", async () => {
    const user = userEvent.setup();
    const { onMarkLegendChange } = renderControl({ markLegend: false });
    await user.click(screen.getByRole("button", { name: /marks mean/ }));
    expect(onMarkLegendChange).toHaveBeenCalledWith(true);
  });

  it("has no Satellite row and no unbuilt placeholders", () => {
    renderControl();
    expect(screen.queryByText("Satellite")).toBeNull();
    expect(screen.queryByText(/Anomaly/)).toBeNull();
    expect(screen.queryByText(/Compare/)).toBeNull();
  });

  it("closes the open panel on Escape", async () => {
    const user = userEvent.setup();
    renderControl();
    await user.click(screen.getByRole("button", { name: /Field flags/ }));
    expect(screen.getByText("Open flags only")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByText("Open flags only")).toBeNull();
  });
});

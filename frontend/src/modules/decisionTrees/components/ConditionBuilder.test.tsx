import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { parseConditionTree } from "../lib/conditionEdit";
import { ConditionBuilder } from "./ConditionBuilder";

// The signals-source dropdown loads the tenant signal catalog; the
// builder itself is what's under test, so stub the network away.
vi.mock("@/api/signals", () => ({
  listSignalDefinitions: () =>
    Promise.resolve([
      {
        code: "leaf_colour",
        value_kind: "categorical",
        categorical_values: ["pale", "normal"],
        description: "Visual leaf colour scored by the scout.",
      },
      { code: "soil_ph", value_kind: "numeric", value_min: "0", value_max: "14", unit: "pH" },
    ]),
}));
vi.mock("@/api/weatherIndices", () => ({
  getWeatherIndexCatalog: () =>
    Promise.resolve([
      {
        code: "rain_et_balance",
        unit: "mm",
        description_en: "Daily water balance: rainfall minus ET0.",
        description_ar: "الميزان المائي اليومي",
      },
    ]),
}));
vi.mock("@/api/crops", () => ({
  listCropAttributeCatalog: () =>
    Promise.resolve([
      {
        code: "transplant_date",
        path: "mango",
        name_en: "Transplant date",
        value_type: "date",
        description_en: "When the block was transplanted.",
      },
      {
        code: "rootstock_type",
        path: "mango",
        name_en: "Rootstock",
        value_type: "single_select",
        options: [{ code: "seedling" }, { code: "grafted" }],
      },
    ]),
}));

function renderBuilder(rawTree: unknown) {
  const onChange = vi.fn();
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <ConditionBuilder value={parseConditionTree(rawTree)} onChange={onChange} />
    </QueryClientProvider>,
  );
  return onChange;
}

const NDVI_LT_0 = {
  op: "lt",
  left: { source: "indices", index_code: "ndvi", key: "baseline_deviation" },
  right: 0,
};

describe("<ConditionBuilder>", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
  });

  it("renders a nested group instead of the YAML fallback", () => {
    renderBuilder({
      all_of: [
        NDVI_LT_0,
        {
          any_of: [
            { op: "gt", left: { source: "indices", index_code: "ndmi", key: "mean" }, right: 1 },
          ],
        },
      ],
    });
    // Two group headers — outer + nested — and no "not available" notice.
    expect(screen.getAllByLabelText("Match")).toHaveLength(2);
    expect(screen.queryByText("Visual editing not available")).not.toBeInTheDocument();
  });

  it("renders a NOT wrapper", () => {
    renderBuilder({ not: NDVI_LT_0 });
    expect(screen.getByText("NOT")).toBeInTheDocument();
    expect(screen.queryByText("Visual editing not available")).not.toBeInTheDocument();
  });

  it("renders between as a From/To pair", () => {
    renderBuilder({
      op: "between",
      left: { source: "indices", index_code: "ndvi", key: "mean" },
      low: 0.2,
      high: 0.8,
    });
    expect(screen.getByDisplayValue("0.2")).toBeInTheDocument();
    expect(screen.getByDisplayValue("0.8")).toBeInTheDocument();
  });

  it("renders in as an editable value list", () => {
    renderBuilder({
      op: "in",
      left: { source: "block", field: "growth_stage" },
      values: ["vegetative", "tuber_bulking"],
    });
    expect(screen.getByDisplayValue("vegetative")).toBeInTheDocument();
    expect(screen.getByDisplayValue("tuber_bulking")).toBeInTheDocument();
  });

  it("offers growth_stage as a block field", () => {
    renderBuilder({ op: "eq", left: { source: "block", field: "growth_stage" }, right: "kimri" });
    expect(screen.getByLabelText("Block field")).toHaveValue("growth_stage");
  });

  it("offers the weather field as a scope-specific dropdown", () => {
    renderBuilder({
      op: "gt",
      left: { source: "weather", scope: "derived_today", field: "precip_mm_7d" },
      right: 5,
    });
    const field = screen.getByLabelText("Weather field");
    expect(field).toHaveValue("precip_mm_7d");
    // The derived-daily vocabulary, not the hourly or forecast one.
    const options = within(field as HTMLSelectElement)
      .getAllByRole("option")
      .map((o) => o.textContent);
    expect(options).toContain("gdd_cumulative_base10_season");
    expect(options).not.toContain("precipitation_mm_total");
  });

  it("moves the field to the new scope's vocabulary when the scope changes", async () => {
    const user = userEvent.setup();
    const onChange = renderBuilder({
      op: "gt",
      left: { source: "weather", scope: "forecast_24h", field: "precipitation_mm_total" },
      right: 5,
    });

    await user.selectOptions(screen.getByDisplayValue("forecast_24h"), "derived_today");

    // `precipitation_mm_total` doesn't exist on the derived daily row, and
    // keeping it would leave a term that can never match.
    const emitted = onChange.mock.calls[0][0] as { left: { scope: string; field: string } };
    expect(emitted.left.scope).toBe("derived_today");
    expect(emitted.left.field).toBe("gdd_base10");
  });

  it("carries the field across the two forecast windows, which share a vocabulary", async () => {
    const user = userEvent.setup();
    const onChange = renderBuilder({
      op: "gt",
      left: { source: "weather", scope: "forecast_24h", field: "air_temp_c_max" },
      right: 40,
    });

    await user.selectOptions(screen.getByDisplayValue("forecast_24h"), "forecast_72h");

    const emitted = onChange.mock.calls[0][0] as { left: { scope: string; field: string } };
    expect(emitted.left).toEqual({
      source: "weather",
      scope: "forecast_72h",
      field: "air_temp_c_max",
    });
  });

  it("keeps a YAML-authored field that isn't in the scope's list selectable", () => {
    renderBuilder({
      op: "gt",
      left: { source: "weather", scope: "latest_observation", field: "some_new_column" },
      right: 1,
    });
    // Not silently dropped — the author can see what the tree actually says.
    expect(screen.getByLabelText("Weather field")).toHaveValue("some_new_column");
  });

  it("retypes the right operand when the left becomes categorical", async () => {
    const user = userEvent.setup();
    const onChange = renderBuilder(NDVI_LT_0);

    await user.selectOptions(screen.getByDisplayValue("Index (NDVI, EVI, …)"), "block");

    // Was `number: 0`, which against a stored string could never match.
    const emitted = onChange.mock.calls[0][0] as { right: unknown; left: unknown };
    expect(emitted.left).toEqual({ source: "block", field: "growth_stage" });
    expect(emitted.right).toBe("");
  });

  it("renders a closed vocabulary as a picker, not a text box", () => {
    renderBuilder({ op: "eq", left: { source: "block", field: "soil_texture" }, right: "clay" });
    const operand = screen.getByDisplayValue("clay");
    expect(operand.tagName).toBe("SELECT");
    const options = within(operand as HTMLSelectElement)
      .getAllByRole("option")
      .map((o) => o.textContent);
    expect(options).toEqual([
      "sandy",
      "sandy_loam",
      "loam",
      "clay_loam",
      "clay",
      "silty_loam",
      "silty_clay",
    ]);
  });

  it("leaves an open-ended categorical as a text box", () => {
    renderBuilder({ op: "eq", left: { source: "block", field: "growth_stage" }, right: "kimri" });
    // Growth stages come from the crop taxonomy — no closed list to offer.
    expect(screen.getByDisplayValue("kimri").tagName).toBe("INPUT");
  });

  it("offers a categorical signal's own options as a closed list", async () => {
    renderBuilder({
      op: "eq",
      left: { source: "signals", code: "leaf_colour", key: "value_categorical" },
      right: "pale",
    });

    // The definition declares the vocabulary; anything else can never match.
    await waitFor(() => expect(screen.getByDisplayValue("pale").tagName).toBe("SELECT"));
    const operand = screen.getByDisplayValue("pale");
    expect(
      within(operand as HTMLSelectElement)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["pale", "normal"]);
  });

  it("warns, but still saves, a threshold outside the recorded range", async () => {
    renderBuilder({
      op: "gt",
      left: { source: "signals", code: "soil_ph", key: "value_numeric" },
      right: 20,
    });

    // 20 is past the definition's max of 14 — advisory only, because "alert if
    // pH goes above 9" on a signal that has never recorded above 8.5 is a
    // legitimate rule.
    expect(await screen.findByText(/Outside the recorded range/)).toBeInTheDocument();
    expect(screen.getByDisplayValue("20")).toBeInTheDocument();
  });

  it("does not warn inside the range", async () => {
    renderBuilder({
      op: "gt",
      left: { source: "signals", code: "soil_ph", key: "value_numeric" },
      right: 7,
    });
    // Let the definition load, then confirm nothing was flagged.
    await waitFor(() => expect(screen.getByDisplayValue("7")).toBeInTheDocument());
    expect(screen.queryByText(/Outside the recorded range/)).not.toBeInTheDocument();
  });

  it("renders a date crop attribute as a date input", async () => {
    renderBuilder({
      op: "lt",
      left: { source: "crop_attribute", code: "transplant_date", key: "value" },
      right: "2024-03-01",
    });
    await waitFor(() =>
      expect(screen.getByDisplayValue("2024-03-01")).toHaveAttribute("type", "date"),
    );
  });

  it("renders a single-select crop attribute as its option list", async () => {
    renderBuilder({
      op: "eq",
      left: { source: "crop_attribute", code: "rootstock_type", key: "value" },
      right: "grafted",
    });
    await waitFor(() => expect(screen.getByDisplayValue("grafted").tagName).toBe("SELECT"));
    const operand = screen.getByDisplayValue("grafted");
    expect(
      within(operand as HTMLSelectElement)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["seedling", "grafted"]);
  });

  it("explains the selected code with a hint from the i18n catalogue", () => {
    renderBuilder(NDVI_LT_0);
    // A code is only self-explanatory to whoever named it.
    expect(screen.getByText(/Canopy greenness and vigour/)).toBeInTheDocument();
    expect(screen.getByText(/Standard deviations from this block/)).toBeInTheDocument();
  });

  it("offers the thermal indices on the indices source, grouped apart", () => {
    // They were computed, stored per block and charted everywhere except
    // here, so a rule could never branch on canopy temperature.
    renderBuilder(NDVI_LT_0);
    const picker = screen.getByLabelText("Index code");
    for (const code of ["lst", "cwsi", "smi"]) {
      expect(within(picker).getByRole("option", { name: code })).toBeInTheDocument();
    }
    // Grouped, because they are a coarser satellite: the label is what tells
    // the author a threshold here is a 100 m reading, not a 10 m one.
    expect(picker.querySelector('optgroup[label="Thermal (Landsat, 100 m)"]')).not.toBeNull();
    expect(picker.querySelector('optgroup[label="Spectral (Sentinel-2, 10 m)"]')).not.toBeNull();
  });

  it("keeps the grid source optical-only", () => {
    // Grid cells are cut per product and only the optical product has a grid
    // config, so a thermal code here is a term that can never resolve.
    renderBuilder({
      op: "ge",
      left: { source: "grid", index_code: "ndvi", field: "flagged_count" },
      right: 5,
    });
    const picker = screen.getByLabelText("Index code");
    expect(within(picker).getByRole("option", { name: "ndvi" })).toBeInTheDocument();
    expect(within(picker).queryByRole("option", { name: "lst" })).not.toBeInTheDocument();
  });

  it("explains a thermal index, including that it is degrees not a ratio", () => {
    renderBuilder({
      op: "gt",
      left: { source: "indices", index_code: "lst", key: "mean" },
      right: 45,
    });
    expect(screen.getByText(/Land surface temperature/)).toBeInTheDocument();
  });

  it("explains a weather field, which differs per scope", () => {
    renderBuilder({
      op: "gt",
      left: { source: "weather", scope: "derived_today", field: "gdd_cumulative_base10_season" },
      right: 500,
    });
    expect(screen.getByText(/Season-to-date accumulated degree days/)).toBeInTheDocument();
  });

  it("uses the tenant's own description for a custom signal", async () => {
    renderBuilder({
      op: "eq",
      left: { source: "signals", code: "leaf_colour", key: "value_categorical" },
      right: "pale",
    });
    // Written by the tenant when they defined the signal — not restated here.
    expect(await screen.findByText(/Visual leaf colour scored by the scout/)).toBeInTheDocument();
  });

  it("uses the platform catalog's description for a weather index", async () => {
    renderBuilder({
      op: "lt",
      left: { source: "weather_index", index_code: "rain_et_balance", key: "value" },
      right: -5,
    });
    expect(await screen.findByText(/Daily water balance/)).toBeInTheDocument();
  });

  it("uses the definition's description for a crop field", async () => {
    renderBuilder({
      op: "lt",
      left: { source: "crop_attribute", code: "transplant_date", key: "value" },
      right: "2024-03-01",
    });
    expect(await screen.findByText(/When the block was transplanted/)).toBeInTheDocument();
  });

  it("renders no hint line at all when a code has no description", () => {
    // An empty muted line under a dropdown is worse than none.
    renderBuilder({
      op: "gt",
      left: { source: "weather", scope: "latest_observation", field: "some_unknown_column" },
      right: 1,
    });
    expect(screen.queryByText(/editor\.condition\.hint/)).not.toBeInTheDocument();
  });

  it("wraps a lone term into a group when a second condition is added", async () => {
    const user = userEvent.setup();
    const onChange = renderBuilder(NDVI_LT_0);

    await user.click(screen.getByRole("button", { name: "+ Add condition" }));

    expect(onChange).toHaveBeenCalledTimes(1);
    const emitted = onChange.mock.calls[0][0] as { all_of?: unknown[] };
    expect(emitted.all_of).toHaveLength(2);
    // The original term survives the wrap rather than being replaced.
    expect(emitted.all_of?.[0]).toEqual(NDVI_LT_0);
  });

  it("emits a nested group when a group is added inside a group", async () => {
    const user = userEvent.setup();
    const onChange = renderBuilder({
      all_of: [
        NDVI_LT_0,
        { op: "gt", left: { source: "indices", index_code: "evi", key: "mean" }, right: 1 },
      ],
    });

    await user.click(screen.getByRole("button", { name: "+ Add group" }));

    const emitted = onChange.mock.calls[0][0] as { all_of?: unknown[] };
    expect(emitted.all_of).toHaveLength(3);
    // Nested group defaults to the opposite mode, which is the useful
    // default: an ANY bundle inside an ALL list.
    expect(emitted.all_of?.[2]).toHaveProperty("any_of");
  });

  it("removing the only child of a group drops the group entirely", async () => {
    const user = userEvent.setup();
    const onChange = renderBuilder({ all_of: [NDVI_LT_0] });

    await user.click(screen.getByRole("button", { name: "Remove condition" }));

    // `undefined` clears the condition rather than leaving `all_of: []`.
    expect(onChange).toHaveBeenCalledWith(undefined);
  });
});

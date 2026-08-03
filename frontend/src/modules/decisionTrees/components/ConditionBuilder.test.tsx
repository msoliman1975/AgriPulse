import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { parseConditionTree } from "../lib/conditionEdit";
import { ConditionBuilder } from "./ConditionBuilder";

// The signals-source dropdown loads the tenant signal catalog; the
// builder itself is what's under test, so stub the network away.
vi.mock("@/api/signals", () => ({
  listSignalDefinitions: () => Promise.resolve([]),
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

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { BetaConditionEditor } from "./BetaConditionEditor";

beforeEach(async () => {
  await setupTestI18n("en");
});

const term = {
  op: "lt",
  left: { source: "indices", index_code: "ndvi", key: "baseline_deviation" },
  right: 0,
};

describe("<BetaConditionEditor>", () => {
  it("offers every operator the engine implements, between included", () => {
    render(<BetaConditionEditor value={term} onChange={vi.fn()} />);
    const op = screen.getByLabelText<HTMLSelectElement>("Operator");
    expect([...op.options].map((o) => o.value)).toEqual([
      "lt",
      "le",
      "gt",
      "ge",
      "eq",
      "ne",
      "between",
      "in",
    ]);
  });

  it("writes a range with both bounds when between is picked", async () => {
    const onChange = vi.fn();
    render(<BetaConditionEditor value={term} onChange={onChange} />);
    await userEvent.selectOptions(screen.getByLabelText("Operator"), "between");
    expect(onChange).toHaveBeenCalledWith({
      op: "between",
      left: term.left,
      low: 0,
      high: 0,
    });
  });

  it("shows a From and a To field for a range, and no single value field", () => {
    render(
      <BetaConditionEditor
        value={{ op: "between", left: term.left, low: 10, high: 30 }}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByLabelText<HTMLInputElement>("From").value).toBe("10");
    expect(screen.getByLabelText<HTMLInputElement>("To").value).toBe("30");
    expect(screen.queryByLabelText("Value")).toBeNull();
  });

  it("keeps a typed bound a number, so the comparison is numeric", async () => {
    const onChange = vi.fn();
    render(
      <BetaConditionEditor
        value={{ op: "between", left: term.left, low: 0, high: 0 }}
        onChange={onChange}
      />,
    );
    await userEvent.type(screen.getByLabelText("To"), "5");
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ op: "between", high: 5 }));
  });

  it("starts an empty condition with one test", async () => {
    const onChange = vi.fn();
    render(<BetaConditionEditor value={undefined} onChange={onChange} />);
    await userEvent.click(screen.getByRole("button", { name: "Add a test" }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ op: "lt" }));
  });

  it("edits a group rather than showing it as text", async () => {
    const onChange = vi.fn();
    render(<BetaConditionEditor value={{ all_of: [term] }} onChange={onChange} />);
    await userEvent.selectOptions(screen.getByLabelText("How the group matches"), "any_of");
    expect(onChange).toHaveBeenCalledWith({ any_of: [term] });
  });

  it("shows a hand-written shape it cannot edit instead of dropping it", () => {
    render(
      <BetaConditionEditor value={{ op: "matches", left: {}, right: "x" }} onChange={vi.fn()} />,
    );
    expect(screen.getByText(/shape the editor does not offer/i)).toBeInTheDocument();
  });

  it("offers no edit controls on a published tree", () => {
    render(<BetaConditionEditor value={term} onChange={vi.fn()} readOnly />);
    expect(screen.queryByRole("button", { name: "Remove" })).toBeNull();
    expect(screen.getByLabelText("Operator")).toBeDisabled();
  });
});

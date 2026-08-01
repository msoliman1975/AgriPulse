import { beforeAll, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { setupTestI18n } from "@/i18n/testing";

import { Toolbar, type FilterAxis, type FilterValues } from "./Toolbar";

const AXES: FilterAxis[] = [
  {
    key: "location",
    label: "Location",
    options: [
      { value: "EG", label: "Egypt" },
      { value: "MA", label: "Morocco" },
    ],
  },
  {
    key: "soil",
    label: "Soil texture",
    options: [
      { value: "sandy", label: "Sandy" },
      { value: "loam", label: "Loam" },
    ],
  },
];

function renderToolbar(values: FilterValues = {}, onValuesChange = vi.fn()) {
  const utils = render(
    <Toolbar
      axes={AXES}
      values={values}
      onValuesChange={onValuesChange}
      resultCount={{ shown: 2, total: 14 }}
    />,
  );
  return { ...utils, onValuesChange };
}

describe("Toolbar", () => {
  beforeAll(async () => {
    await setupTestI18n("en");
  });

  it("hides the filter menu until the trigger is used", async () => {
    renderToolbar();
    expect(screen.queryByRole("group", { name: "Location" })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Filters/ }));
    expect(screen.getByRole("group", { name: "Location" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Soil texture" })).toBeInTheDocument();
  });

  it("closes on Escape and returns focus to the trigger", async () => {
    renderToolbar();
    const trigger = screen.getByRole("button", { name: /Filters/ });

    await userEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");

    await userEvent.keyboard("{Escape}");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).toHaveFocus();
  });

  it("counts active filters on the trigger badge", () => {
    renderToolbar({ location: ["EG"], soil: ["sandy"] });
    expect(screen.getByRole("button", { name: /Filters/ })).toHaveTextContent("2");
  });

  it("echoes applied filters back as removable chips", async () => {
    const { onValuesChange } = renderToolbar({ location: ["EG"] });

    const chip = screen.getByRole("button", { name: /Remove filter Egypt/ });
    await userEvent.click(chip);

    expect(onValuesChange).toHaveBeenCalledWith({ location: [] });
  });

  it("reports the result count alongside the applied filters", () => {
    renderToolbar({ location: ["EG"] });
    expect(screen.getByText("Showing 2 of 14")).toBeInTheDocument();
  });

  it("toggles a value on and off within a multi-select axis", async () => {
    const onValuesChange = vi.fn();
    render(<Toolbar axes={AXES} values={{ location: ["EG"] }} onValuesChange={onValuesChange} />);

    await userEvent.click(screen.getByRole("button", { name: /Filters/ }));
    await userEvent.click(screen.getByRole("checkbox", { name: "Morocco" }));

    expect(onValuesChange).toHaveBeenCalledWith({ location: ["EG", "MA"] });
  });

  it("clears everything from the applied-filter row", async () => {
    const { onValuesChange } = renderToolbar({ location: ["EG"], soil: ["loam"] });

    await userEvent.click(screen.getByRole("button", { name: "Clear all" }));
    expect(onValuesChange).toHaveBeenCalledWith({});
  });
});

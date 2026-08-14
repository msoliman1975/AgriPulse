import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { Table, Tbody, Td, Th, Thead, Tr } from "./Table";
import { Tooltip } from "./Tooltip";

describe("Tooltip", () => {
  it("reveals its content on hover", async () => {
    const user = userEvent.setup();
    render(
      <Tooltip content="Documentation only.">
        <button type="button">Scope</button>
      </Tooltip>,
    );
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    await user.hover(screen.getByRole("button", { name: "Scope" }));
    expect(await screen.findByRole("tooltip")).toHaveTextContent("Documentation only.");
  });

  it("reveals its content on keyboard focus, not just hover", async () => {
    const user = userEvent.setup();
    render(
      <Tooltip content="Documentation only.">
        <button type="button">Scope</button>
      </Tooltip>,
    );
    await user.tab();
    expect(await screen.findByRole("tooltip")).toBeInTheDocument();
  });

  /**
   * The prod bug. `Table` wraps every table in `overflow-x-auto`, and CSS
   * promotes the other axis to a clipping value when one axis is `auto`. An
   * absolutely-positioned bubble above a `<thead>` cell was drawn outside that
   * box and clipped away entirely, so a column-header hint showed nothing at
   * all — only the `cursor-help` question-mark cursor. `fixed` escapes every
   * clipping ancestor, so this is the property worth pinning.
   */
  it("escapes a scroll container so a table-header hint is not clipped", async () => {
    const user = userEvent.setup();
    render(
      <Table>
        <Thead>
          <Tr>
            <Th>
              <Tooltip content="Which layer of the token can grant this.">
                <button type="button">Scope</button>
              </Tooltip>
            </Th>
          </Tr>
        </Thead>
        <Tbody>
          <Tr>
            <Td>farm.read</Td>
          </Tr>
        </Tbody>
      </Table>,
    );

    await user.hover(screen.getByRole("button", { name: "Scope" }));
    const tip = await screen.findByRole("tooltip");

    expect(tip).toHaveTextContent("Which layer of the token can grant this.");
    // Not `absolute`: that is what put it inside the clipped box.
    expect(tip.className).toContain("fixed");
    expect(tip.className).not.toContain("absolute");
    // Positioned from the trigger's measured rect rather than by CSS offsets.
    expect(tip.style.transform).toBe("translate(-50%, -100%)");
  });

  it("hides again when the pointer leaves", async () => {
    const user = userEvent.setup();
    render(
      <Tooltip content="Documentation only.">
        <button type="button">Scope</button>
      </Tooltip>,
    );
    const trigger = screen.getByRole("button", { name: "Scope" });
    await user.hover(trigger);
    expect(await screen.findByRole("tooltip")).toBeInTheDocument();
    await user.unhover(trigger);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });
});

/**
 * The block-health rollup choice: what it sends, and in which order.
 *
 * The settings rows copy the shape `GET /v1/integrations/detection/tenant`
 * returns (`ResolvedIntegrationSetting` in
 * `backend/app/modules/integrations/schemas.py`).
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";
import type { ResolvedSetting } from "@/api/integrations";

import { CELL_ROLLUP_KEY, CELL_SHARE_KEY, CellRollupCard } from "./CellRollupCard";

function setting(key: string, value: unknown): ResolvedSetting {
  return { key, value, source: "platform", overridden_at: null };
}

describe("CellRollupCard", () => {
  beforeEach(async () => {
    await setupTestI18n();
  });

  it("starts on the stored rule and hides the percent unless the rule is share", async () => {
    render(
      <CellRollupCard
        rollup={setting(CELL_ROLLUP_KEY, "worst")}
        share={setting(CELL_SHARE_KEY, 20)}
        onSave={vi.fn()}
      />,
    );
    expect(await screen.findByRole("radio", { name: /The worst cell decides/ })).toBeChecked();
    expect(screen.queryByLabelText("Share of cells (%)")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("saves the percent before the rule when switching to share", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(
      <CellRollupCard
        rollup={setting(CELL_ROLLUP_KEY, "worst")}
        share={setting(CELL_SHARE_KEY, 20)}
        onSave={onSave}
      />,
    );
    await user.click(
      await screen.findByRole("radio", { name: /The worst status on a share of the cells/ }),
    );
    const pct = screen.getByLabelText("Share of cells (%)");
    await user.clear(pct);
    await user.type(pct, "35");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(2));
    expect(onSave.mock.calls).toEqual([
      [CELL_SHARE_KEY, 35],
      [CELL_ROLLUP_KEY, "share"],
    ]);
    expect(await screen.findByText(/Saved/)).toBeInTheDocument();
  });

  it("refuses a percent outside 1 to 100", async () => {
    const user = userEvent.setup();
    render(
      <CellRollupCard
        rollup={setting(CELL_ROLLUP_KEY, "share")}
        share={setting(CELL_SHARE_KEY, 20)}
        onSave={vi.fn()}
      />,
    );
    const pct = await screen.findByLabelText("Share of cells (%)");
    await user.clear(pct);
    await user.type(pct, "0");
    expect(screen.getByText("Enter a whole number from 1 to 100.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });
});

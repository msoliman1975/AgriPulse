import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getHealthTemplate, putHealthTemplate } from "@/api/farmConfig";
import { setupTestI18n } from "@/i18n/testing";

import { FarmHealthPanel } from "./FarmHealthPanel";

vi.mock("@/api/farmConfig", async () => {
  const actual = await vi.importActual<typeof import("@/api/farmConfig")>("@/api/farmConfig");
  return { ...actual, getHealthTemplate: vi.fn(), putHealthTemplate: vi.fn() };
});

const FARM_ID = "11111111-1111-1111-1111-111111111111";

function load(definition: Record<string, unknown> | null, locked = false) {
  vi.mocked(getHealthTemplate).mockResolvedValue({ definition, locked });
  vi.mocked(putHealthTemplate).mockImplementation((_id, body) =>
    Promise.resolve({ definition: body, locked: false }),
  );
  render(<FarmHealthPanel farmId={FARM_ID} />);
}

describe("FarmHealthPanel", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    vi.mocked(getHealthTemplate).mockReset();
    vi.mocked(putHealthTemplate).mockReset();
  });

  it("shows every setting as inherited when the farm has no override", async () => {
    load(null);
    await waitFor(() => expect(screen.getByText("Health definition")).toBeTruthy());

    // Seven settings, seven "Inherited" markers. A control that rendered a
    // VALUE here would read as a farm decision that has not been made.
    expect(screen.getAllByText("Inherited")).toHaveLength(7);
    expect(screen.getByText("Nothing overridden on this farm.")).toBeTruthy();
  });

  it("counts the overrides in words, singular and plural", async () => {
    // i18next needs `_one` / `_other`; a bare key renders the raw key string
    // and reads as a bug on screen. Asserting the SENTENCE catches that.
    load({ stale_after_hours: 72 });
    await waitFor(() => expect(screen.getByText("Health definition")).toBeTruthy());
    expect(screen.getByText("1 setting overridden on this farm.")).toBeTruthy();

    await userEvent.click(screen.getByLabelText("Blocks no tree covers"));
    expect(screen.getByText("2 settings overridden on this farm.")).toBeTruthy();
  });

  it("sends only the setting that was switched on", async () => {
    // The whole point of the panel. Sending all seven would pin six values
    // the operator never chose and stop the farm tracking the crop defaults.
    load(null);
    await waitFor(() => expect(screen.getByText("Health definition")).toBeTruthy());

    await userEvent.click(screen.getByLabelText("Trust a clear result for"));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(putHealthTemplate).toHaveBeenCalled());
    expect(vi.mocked(putHealthTemplate).mock.calls[0][1]).toEqual({ stale_after_hours: 48 });
  });

  it("clears the override rather than saving an empty body", async () => {
    // NULL says the farm follows the knowledge base; `{}` would say it has
    // decided and stop it tracking. The two must not be confused.
    load({ stale_after_hours: 72 });
    await waitFor(() => expect(screen.getByText("Health definition")).toBeTruthy());

    await userEvent.click(screen.getByRole("button", { name: "Clear all" }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(putHealthTemplate).toHaveBeenCalled());
    expect(vi.mocked(putHealthTemplate).mock.calls[0][1]).toBeNull();
  });

  it("treats a stored null as overridden, not as absent", async () => {
    // `snoozed_as: null` is a real choice — "count a snoozed alert by its
    // own severity". Reading it back as inherited would silently drop it on
    // the next save.
    load({ snoozed_as: null });
    await waitFor(() => expect(screen.getByText("Health definition")).toBeTruthy());

    expect(screen.getAllByText("Inherited")).toHaveLength(6);
    expect(screen.getByDisplayValue("Its own severity")).toBeTruthy();

    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(putHealthTemplate).toHaveBeenCalled());
    expect(vi.mocked(putHealthTemplate).mock.calls[0][1]).toEqual({ snoozed_as: null });
  });

  it("round-trips a stored override without changing it", async () => {
    load({ stale_after_hours: 72 });
    await waitFor(() => expect(screen.getByText("Health definition")).toBeTruthy());

    expect(screen.getByDisplayValue("72")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(putHealthTemplate).toHaveBeenCalled());
    expect(vi.mocked(putHealthTemplate).mock.calls[0][1]).toEqual({ stale_after_hours: 72 });
  });

  it("edits a share as a percentage and sends it as a fraction", async () => {
    load({ cell_critical_share: 0.25 });
    await waitFor(() => expect(screen.getByText("Health definition")).toBeTruthy());

    // A grower says "a quarter of the cells", not "0.25".
    expect(screen.getByDisplayValue("25")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(putHealthTemplate).toHaveBeenCalled());
    expect(vi.mocked(putHealthTemplate).mock.calls[0][1]).toEqual({ cell_critical_share: 0.25 });
  });

  it("offers only legal values", async () => {
    load({ no_tree_coverage: "unknown" });
    await waitFor(() => expect(screen.getByText("Health definition")).toBeTruthy());

    // Two options and not four: `watch` and `critical` are not answers to
    // "no tree applies", and the server refuses them. A control must not be
    // able to reach a value it will be told off for.
    const select = screen.getByDisplayValue<HTMLSelectElement>("Unknown");
    expect([...select.options].map((o) => o.value)).toEqual(["unknown", "healthy"]);
  });

  it("says the farm is locked and disables the controls", async () => {
    load({ stale_after_hours: 72 }, true);
    await waitFor(() => expect(screen.getByText("Health definition")).toBeTruthy());

    expect(
      screen.getByText("This farm's health definition is locked. Unlock it before editing."),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Save" })).toHaveProperty("disabled", true);
  });

  it("renders in Arabic", async () => {
    await setupTestI18n("ar");
    load(null);
    // The rendered string, not the key. A missing translation would leave
    // "farmHealth.title" on screen and a key-level assertion would pass.
    await waitFor(() => expect(screen.getByText("تعريف الحالة")).toBeTruthy());
    expect(screen.getAllByText("موروث")).toHaveLength(7);
  });
});

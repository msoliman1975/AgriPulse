// A pinned tenant must be able to unpin.
//
// The select's "follow the current version" option carries the empty string,
// and the panel also used the empty string to mean "the author has not touched
// this yet, show what is stored". Those two are not the same thing, and
// collapsing them meant choosing "follow the current version" fell back to the
// stored pin: the select snapped back to it and Apply re-pinned the same
// version. The API's DELETE was never reached, so a tenant that pinned a tree
// could not unpin it from this page at all.
//
// The mutation call is what is asserted here, not the select's value. Asserting
// the value would pass on a panel that displays correctly and still sends the
// wrong request.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { TreeRolloutPanel } from "./TreeRolloutPanel";

const state = vi.hoisted(() => ({ pinnedVersion: null as number | null }));
const setPin = vi.hoisted(() => vi.fn());

vi.mock("@/queries/decisionTrees", () => ({
  useDecisionTreeAvailability: () => ({
    isLoading: false,
    isError: false,
    data: {
      code: "qa_tree",
      farms_running: 2,
      farms_total: 2,
      enabled_everywhere: true,
      current_version: 5,
      pinned_version: state.pinnedVersion,
    },
  }),
  useSetDecisionTreeEnabled: () => ({ mutate: vi.fn(), isPending: false, isError: false }),
  useSetDecisionTreeVersionPin: () => ({ mutate: setPin, isPending: false, isError: false }),
}));

const VERSIONS = [
  { version: 5, published_at: "2026-09-01T00:00:00Z" },
  { version: 4, published_at: "2026-08-01T00:00:00Z" },
  // A draft. A pin to it would drop the tree out of the sweep, so it must not
  // be offered.
  { version: 6, published_at: null },
] as never;

function renderPanel(): void {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <TreeRolloutPanel code="qa_tree" canManage versions={VERSIONS} />
    </QueryClientProvider>,
  );
}

describe("TreeRolloutPanel version pin", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    setPin.mockClear();
  });

  it("sends a clear, not a re-pin, when a pinned tenant picks follow-the-current", async () => {
    state.pinnedVersion = 4;
    renderPanel();

    const select = await screen.findByLabelText(/version to hold/i);
    // The empty-string option is "follow the current version".
    fireEvent.change(select, { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: /apply/i }));

    await waitFor(() => expect(setPin).toHaveBeenCalledTimes(1));
    expect(setPin).toHaveBeenCalledWith({ code: "qa_tree", version: null });
  });

  it("still pins when a version is chosen", async () => {
    state.pinnedVersion = null;
    renderPanel();

    const select = await screen.findByLabelText(/version to hold/i);
    fireEvent.change(select, { target: { value: "4" } });
    fireEvent.click(screen.getByRole("button", { name: /apply/i }));

    await waitFor(() => expect(setPin).toHaveBeenCalledTimes(1));
    expect(setPin).toHaveBeenCalledWith({ code: "qa_tree", version: 4 });
  });

  it("offers only published versions", async () => {
    state.pinnedVersion = null;
    renderPanel();

    const select = await screen.findByLabelText(/version to hold/i);
    const values = Array.from(select.querySelectorAll("option")).map((o) => o.value);
    expect(values).toContain("5");
    expect(values).toContain("4");
    expect(values).not.toContain("6");
  });

  it("keeps the new-farm caveat out of the way while the tree is running", () => {
    state.pinnedVersion = null;
    renderPanel();

    // The caveat is only shown when nothing is running, which is the moment
    // the surprise would otherwise land.
    expect(screen.queryByText(/farm you add later/i)).toBeNull();
  });
});

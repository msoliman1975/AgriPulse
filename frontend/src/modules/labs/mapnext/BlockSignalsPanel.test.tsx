import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";
import type { SignalDefinition } from "@/api/signals";

import { BlockSignalsPanel } from "./BlockSignalsPanel";

const BLOCK_ID = "019fe30e-12f2-79f0-994e-2a57f7d94d3c";
const FARM_ID = "019fe30d-c475-79fe-9de0-81df066f971d";

const caps = vi.hoisted(() => ({ record: true, delete: false }));
vi.mock("@/rbac/useCapability", () => ({
  useCapability: (cap: string) => (cap === "signal.record" ? caps.record : caps.delete),
}));

const listObservations = vi.hoisted(() => vi.fn());
const createObservation = vi.hoisted(() => vi.fn());
const listDefinitions = vi.hoisted(() => vi.fn());

vi.mock("@/api/signals", async () => {
  const actual = await vi.importActual<typeof import("@/api/signals")>("@/api/signals");
  return {
    ...actual,
    listSignalDefinitions: (...a: unknown[]) => listDefinitions(...a),
    listSignalObservations: (...a: unknown[]) => listObservations(...a),
    createSignalObservation: (...a: unknown[]) => createObservation(...a),
  };
});

// The list's block filter is hidden when pinned, so its blocks query must
// never fire — asserting on the mock proves the `enabled` guard, not just
// that the <select> is absent.
const listBlocks = vi.hoisted(() => vi.fn());
vi.mock("@/api/blocks", async () => {
  const actual = await vi.importActual<typeof import("@/api/blocks")>("@/api/blocks");
  return { ...actual, listBlocks: (...a: unknown[]) => listBlocks(...a) };
});

const BRIX: SignalDefinition = {
  id: "def-brix",
  code: "fruit_tss_brix",
  name: "Fruit TSS (Brix)",
  description: null,
  value_kind: "numeric",
  unit: "°Bx",
  categorical_values: null,
  value_min: null,
  value_max: null,
  attachment_allowed: false,
  is_active: true,
  aggregation: "latest",
  aggregation_window_days: null,
  tenant_id: null,
} as unknown as SignalDefinition;

function wrap(node: ReactNode): ReactNode {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{node}</QueryClientProvider>;
}

describe("BlockSignalsPanel", () => {
  beforeEach(async () => {
    await setupTestI18n();
    caps.record = true;
    caps.delete = false;
    listDefinitions.mockReset().mockResolvedValue([BRIX]);
    listObservations.mockReset().mockResolvedValue([]);
    createObservation.mockReset().mockResolvedValue({ id: "obs-1" });
    listBlocks.mockReset().mockResolvedValue({ items: [] });
  });

  it("records against the panel's block without asking the user to pick one", async () => {
    render(wrap(<BlockSignalsPanel blockId={BLOCK_ID} farmId={FARM_ID} />));

    // Numeric signals render a plain text box (inputMode="decimal"), not a
    // spinbutton — query by its label so a widget swap can't silently pass.
    const value = await screen.findByLabelText(/value/i);
    fireEvent.change(value, { target: { value: "7.4" } });
    fireEvent.click(screen.getByRole("button", { name: /record/i }));

    await waitFor(() => expect(createObservation).toHaveBeenCalled());
    const [definitionId, payload] = createObservation.mock.calls[0] as [
      string,
      { farm_id: string; block_id: string; value_numeric: string },
    ];
    expect(definitionId).toBe("def-brix");
    expect(payload.block_id).toBe(BLOCK_ID);
    expect(payload.farm_id).toBe(FARM_ID);
    expect(payload.value_numeric).toBe("7.4");
  });

  it("pins the history to this block and drops the block filter", async () => {
    render(wrap(<BlockSignalsPanel blockId={BLOCK_ID} farmId={FARM_ID} />));

    await waitFor(() => expect(listObservations).toHaveBeenCalled());
    const params = listObservations.mock.calls[0][0] as { farm_id: string; block_id?: string };
    expect(params.block_id).toBe(BLOCK_ID);
    expect(params.farm_id).toBe(FARM_ID);
    expect(listBlocks).not.toHaveBeenCalled();
  });

  it("hides the capture form when the user cannot record on this farm", async () => {
    caps.record = false;
    render(wrap(<BlockSignalsPanel blockId={BLOCK_ID} farmId={FARM_ID} />));

    await screen.findByText(/permission/i);
    expect(screen.queryByRole("button", { name: /^record$/i })).toBeNull();
    // History stays visible — read and write are separate capabilities.
    await waitFor(() => expect(listObservations).toHaveBeenCalled());
  });
});

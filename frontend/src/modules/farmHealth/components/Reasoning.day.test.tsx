/**
 * The reasoning panel follows the day on the map.
 *
 * Reported on 2026-10-04: a 28 September 2026 image showed "Checked on
 * 2026-01-25". The panel asked for the verdict's latest check of all and
 * said nothing when that check was older than the day on screen.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { ReasoningDayContext } from "../lib/reasoningDay";
import { dayOfIso } from "../lib/window";
import { Reasoning } from "./Reasoning";

const getVerdictReasoning = vi.fn();

vi.mock("@/rbac/useCapability", () => ({ useCapability: () => true }));
vi.mock("@/api/farmHealth", async () => {
  const actual = await vi.importActual<typeof import("@/api/farmHealth")>("@/api/farmHealth");
  return { ...actual, getVerdictReasoning: (...args: unknown[]) => getVerdictReasoning(...args) };
});

function walk(evaluatedAt: string) {
  return {
    verdict_id: "v1",
    block_id: "b1",
    reasoning_available: true,
    node_path: [],
    resolved_values: {},
    param_overrides: {},
    narrative_en: `Checked on ${evaluatedAt.slice(0, 10)}. The tree checked 5 things, in this order.`,
    narrative_ar: "",
    evaluated_at: evaluatedAt,
    leaf_label_en: null,
    leaf_label_ar: null,
  };
}

function renderOn(day: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ReasoningDayContext.Provider value={dayOfIso(day)}>
        <Reasoning
          blockId="b1"
          verdictId="v1"
          farmId="f1"
          leafNodeId="stop"
          kind="recommendation"
          statusCode="issue"
          statuses={[]}
        />
      </ReasoningDayContext.Provider>
    </QueryClientProvider>,
  );
}

describe("Reasoning on a chosen day", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    getVerdictReasoning.mockReset();
  });

  it("asks for the check at the end of that day", async () => {
    getVerdictReasoning.mockResolvedValue(walk("2026-09-28T10:00:00Z"));
    renderOn("2026-09-28");
    await screen.findByText(/Checked on 2026-09-28/);
    expect(getVerdictReasoning).toHaveBeenCalledWith("b1", "v1", "f1", "2026-09-28T23:59:59.999Z");
    expect(screen.queryByText(/No check has run/)).not.toBeInTheDocument();
  });

  it("says so when the latest check is older than the day", async () => {
    getVerdictReasoning.mockResolvedValue(walk("2026-01-25T10:00:00Z"));
    renderOn("2026-09-28");
    const note = await screen.findByText(/^No check has run on .+ yet\. This is the latest check/);
    // The words around the dates are the claim; the dates themselves are
    // formatted by the browser's locale data, so only their parts are pinned.
    expect(note.textContent).toMatch(/Sep.*28.*2026/);
    expect(note.textContent).toMatch(/Jan.*25.*2026/);
  });
});

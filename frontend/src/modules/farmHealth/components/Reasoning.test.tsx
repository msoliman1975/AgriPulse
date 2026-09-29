/**
 * A reader without `verdict.reasoning.read` is told so, and the walk is never
 * asked for: the route would answer 403, and an error box reads as a fault.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { Reasoning } from "./Reasoning";

const getVerdictReasoning = vi.fn();

vi.mock("@/rbac/useCapability", () => ({ useCapability: () => false }));
vi.mock("@/api/farmHealth", async () => {
  const actual = await vi.importActual<typeof import("@/api/farmHealth")>("@/api/farmHealth");
  return { ...actual, getVerdictReasoning: (...args: unknown[]) => getVerdictReasoning(...args) };
});

describe("Reasoning without the permission", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    getVerdictReasoning.mockClear();
  });

  it("says the role does not include it and does not ask for the walk", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <Reasoning
          blockId="b1"
          verdictId="v1"
          farmId="f1"
          leafNodeId="stop"
          kind="recommendation"
          statusCode="issue"
          statuses={[]}
        />
      </QueryClientProvider>,
    );
    expect(
      await screen.findByText("Your role does not include seeing how the tree decided."),
    ).toBeInTheDocument();
    expect(getVerdictReasoning).not.toHaveBeenCalled();
  });
});

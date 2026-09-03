import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { BlockHealthRow, HealthReason } from "@/api/insights";
import { getFarmHealthSummary } from "@/api/insights";
import { setupTestI18n } from "@/i18n/testing";

import { BlockHealthScorecard } from "./BlockHealthScorecard";

// The scorecard's first test file. It had none, which is how the two
// surfaces that render a block's health drifted apart unnoticed for as long
// as they did.

vi.mock("@/api/insights", async () => {
  const actual = await vi.importActual<typeof import("@/api/insights")>("@/api/insights");
  return { ...actual, getFarmHealthSummary: vi.fn() };
});

const FARM_ID = "11111111-1111-1111-1111-111111111111";

function row(
  name: string,
  health: BlockHealthRow["current_health"],
  reason: HealthReason | null,
): BlockHealthRow {
  return {
    block_id: `${name}-id`,
    block_name: name,
    block_name_ar: null,
    current_health: health,
    health_reason: reason,
    current_value: "0.3100000000",
    trend_30d_pct: null,
    alerts_open: 0,
    last_observation_at: "2026-09-01T00:00:00Z",
  };
}

function renderCard(rows: BlockHealthRow[]) {
  vi.mocked(getFarmHealthSummary).mockResolvedValue({
    farm_id: FARM_ID,
    index_code: "ndvi",
    blocks: rows,
  });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <BlockHealthScorecard farmId={FARM_ID} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("BlockHealthScorecard", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    vi.mocked(getFarmHealthSummary).mockReset();
  });

  it("says why a block is in its health class", async () => {
    renderCard([row("North", "unknown", "no_coverage")]);

    await waitFor(() => expect(screen.getByText("North")).toBeTruthy());
    expect(screen.getByText("Unknown")).toBeTruthy();
    // The sentence, not the code. A missing translation would leave
    // "common:healthReason.no_coverage" on screen and a code-level assertion
    // would still pass.
    expect(screen.getByText("No decision tree has run on this block")).toBeTruthy();
  });

  it("renders exactly as before when the server sent no reason", async () => {
    // `health_definition_enabled` off. The row must be unchanged, because
    // this page ships to every tenant whether or not the flag is on for them.
    renderCard([row("North", "critical", null)]);

    await waitFor(() => expect(screen.getByText("North")).toBeTruthy());
    expect(screen.getByText("Critical")).toBeTruthy();
    expect(screen.queryByText(/decision tree/i)).toBeNull();
  });

  it("keeps showing the NDVI reading when health no longer comes from it", async () => {
    // NDVI leaves the rule, not the page. The column is a measurement and
    // the operator still reads it; blanking it would be a second, silent
    // change riding along with the first.
    renderCard([row("North", "healthy", "all_clear")]);

    await waitFor(() => expect(screen.getByText("North")).toBeTruthy());
    expect(screen.getByText("0.31")).toBeTruthy();
    expect(screen.getByText("Every check passed")).toBeTruthy();
  });

  it("uses the same wording the block dock uses", async () => {
    // Both read `common:healthReason.*`. This is the assertion that fails if
    // somebody copies the strings into the insights namespace: the copy
    // would render here and the dock would keep the original, and one block
    // would be described two ways on two pages.
    const common = (await import("@/i18n/locales/en/common.json")).default as {
      healthReason: Record<string, string>;
    };
    renderCard([row("North", "watch", "cell_share")]);

    await waitFor(() => expect(screen.getByText("North")).toBeTruthy());
    expect(screen.getByText(common.healthReason.cell_share)).toBeTruthy();
  });

  it("translates the reason", async () => {
    await setupTestI18n("ar");
    renderCard([row("North", "healthy", "all_clear")]);

    await waitFor(() => expect(screen.getByText("North")).toBeTruthy());
    expect(screen.getByText("اجتازت كل الفحوصات")).toBeTruthy();
  });
});

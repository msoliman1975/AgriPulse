import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";
import type {
  BlockIntegrationHealth,
  FarmIntegrationHealth,
  IntegrationAttempt,
} from "@/api/integrationsHealth";

import { OverviewTab } from "./OverviewTab";

const FARM_ID = "019fe30d-c475-79fe-9de0-81df066f971d";
const BLOCK_ID = "019fe30e-12f2-79f0-994e-2a57f7d94d3c";

const listFarmHealth = vi.hoisted(() => vi.fn());
const listBlockHealth = vi.hoisted(() => vi.fn());
const listBlockAttempts = vi.hoisted(() => vi.fn());

vi.mock("@/api/integrationsHealth", async () => {
  const actual = await vi.importActual<typeof import("@/api/integrationsHealth")>(
    "@/api/integrationsHealth",
  );
  return {
    ...actual,
    listFarmHealth: (...a: unknown[]) => listFarmHealth(...a),
    listBlockHealth: (...a: unknown[]) => listBlockHealth(...a),
    listBlockAttempts: (...a: unknown[]) => listBlockAttempts(...a),
  };
});

const FARM: FarmIntegrationHealth = {
  farm_id: FARM_ID,
  farm_name: "Mango Republic",
  weather_active_subs: 1,
  weather_last_sync_at: new Date(Date.now() - 8 * 60_000).toISOString(),
  weather_last_failed_at: null,
  imagery_active_subs: 2,
  imagery_last_sync_at: new Date(Date.now() - 2 * 3600_000).toISOString(),
  imagery_failed_24h: 0,
  weather_failed_24h: 0,
  weather_running_count: 0,
  imagery_running_count: 0,
  weather_overdue_count: 0,
  imagery_overdue_count: 0,
};

/**
 * A block on a farm that acquires as one AOI. It owns no subscription rows
 * of its own; migration 0088 is what makes the counts non-zero here.
 */
const BLOCK: BlockIntegrationHealth = {
  block_id: BLOCK_ID,
  farm_id: FARM_ID,
  block_name: "028",
  weather_active_subs: 1,
  weather_last_sync_at: FARM.weather_last_sync_at,
  weather_last_failed_at: null,
  imagery_active_subs: 2,
  imagery_last_sync_at: FARM.imagery_last_sync_at,
  imagery_failed_24h: 0,
  weather_failed_24h: 0,
  weather_running_count: 0,
  imagery_running_count: 0,
  weather_overdue_count: 0,
  imagery_overdue_count: 0,
};

const FARM_RUN: IntegrationAttempt = {
  attempt_id: "019fe30f-0000-7000-8000-000000000001",
  kind: "imagery",
  scope: "farm",
  subscription_id: "019fe30f-0000-7000-8000-000000000002",
  block_id: null,
  farm_id: FARM_ID,
  provider_code: "s2_l2a",
  started_at: new Date(Date.now() - 3 * 3600_000).toISOString(),
  queued_at: null,
  completed_at: null,
  status: "failed",
  duration_ms: null,
  wait_ms: null,
  run_ms: null,
  rows_ingested: null,
  error_code: "provider_error",
  error_message: "upstream 502",
  scene_id: null,
  failed_streak_position: 1,
};

function wrap(node: ReactNode): ReactNode {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{node}</QueryClientProvider>;
}

async function openBlocksTab(): Promise<void> {
  render(wrap(<OverviewTab basePath="/v1" />));
  fireEvent.click(await screen.findByRole("radio", { name: /blocks/i }));
  const picker = await screen.findByRole("combobox");
  fireEvent.change(picker, { target: { value: FARM_ID } });
}

describe("OverviewTab - Blocks", () => {
  beforeEach(async () => {
    await setupTestI18n();
    listFarmHealth.mockReset().mockResolvedValue([FARM]);
    listBlockHealth.mockReset().mockResolvedValue([BLOCK]);
    listBlockAttempts.mockReset().mockResolvedValue([FARM_RUN]);
  });

  it("says when a block last synced instead of calling it unconfigured", async () => {
    // "No active subscription" is what 36 blocks on Valley Farms printed
    // while their farm had synced minutes earlier. The assertion is on the
    // rendered string because that string is the whole defect.
    await openBlocksTab();

    expect(await screen.findByText("028")).toBeInTheDocument();
    expect(screen.queryByText(/no active subscription/i)).toBeNull();
    expect(screen.getAllByText(/synced/i).length).toBeGreaterThan(0);
  });

  it("opens the run log for one block, including its farm-scoped runs", async () => {
    // The endpoint has existed since PR-IH3 and no component called it, so
    // a reader who saw a red block had nowhere to go.
    await openBlocksTab();
    fireEvent.click(await screen.findByRole("button", { name: /^runs$/i }));

    await waitFor(() => expect(listBlockAttempts).toHaveBeenCalled());
    const [blockId] = listBlockAttempts.mock.calls[0] as [string];
    expect(blockId).toBe(BLOCK_ID);
    expect(await screen.findByText("provider_error")).toBeInTheDocument();
    // A whole-farm run is labelled as one, not left with an empty block cell.
    expect(screen.getByText(/whole farm/i)).toBeInTheDocument();
  });

  it("closes the run log again", async () => {
    await openBlocksTab();
    fireEvent.click(await screen.findByRole("button", { name: /^runs$/i }));
    expect(await screen.findByText("provider_error")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /hide/i }));
    await waitFor(() => expect(screen.queryByText("provider_error")).toBeNull());
  });
});

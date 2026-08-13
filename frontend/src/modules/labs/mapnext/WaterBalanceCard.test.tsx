import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";
import { WaterBalanceCard } from "./WaterBalanceCard";

vi.mock("@/api/irrigation", () => ({ getWaterBalance: vi.fn() }));

function wrap(node: ReactNode): ReactNode {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{node}</QueryClientProvider>;
}

function day(over: Record<string, unknown> = {}) {
  return {
    date: "2026-07-01",
    balance_mm: "-6.60",
    etc_mm: "6.60",
    et0_mm: "6.00",
    kc_used: "1.10",
    kc_source: "phenology",
    growth_stage: "flowering",
    precip_mm: "0.00",
    irrigation_mm: "0.00",
    irrigation_logged: true,
    ...over,
  };
}

async function renderWith(rows: unknown[]) {
  const { getWaterBalance } = await import("@/api/irrigation");
  vi.mocked(getWaterBalance).mockResolvedValue(rows as never);
  render(wrap(<WaterBalanceCard blockId="b1" />));
}

describe("WaterBalanceCard", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    await setupTestI18n();
  });

  it("shows the latest balance and the derivation behind it", async () => {
    await renderWith([day({ date: "2026-06-30" }), day()]);
    // The headline is the LAST row, not the first — the series is ascending.
    await waitFor(() => expect(screen.getByText("-6.6 mm")).toBeTruthy());
    // The answer alone is not actionable, so the terms are on screen too.
    expect(screen.getByText("6.6 mm")).toBeTruthy(); // crop used
    expect(screen.getByText("1.10")).toBeTruthy(); // Kc
  });

  it("warns instead of reporting a shortfall when no irrigation was logged", async () => {
    // The case that would otherwise train operators to ignore this card: a
    // farm that never records irrigation shows a permanent deficit which is
    // missing bookkeeping, not dry soil.
    await renderWith([day({ irrigation_logged: false })]);
    await waitFor(() => expect(screen.getByText(/missing bookkeeping/i)).toBeTruthy());
    expect(screen.getByText(/not logged/i)).toBeTruthy();
  });

  it("says nothing about bookkeeping when irrigation IS logged", async () => {
    await renderWith([day({ irrigation_logged: true, irrigation_mm: "8.00" })]);
    await waitFor(() => expect(screen.getByText("8.0 mm")).toBeTruthy());
    expect(screen.queryByText(/missing bookkeeping/i)).toBeNull();
  });

  it("flags a Kc that fell back to the generic default", async () => {
    // A balance built on the generic 0.85 deserves less confidence than one
    // built on a per-stage catalog value, and they look identical otherwise.
    await renderWith([day({ kc_source: "generic_default", kc_used: "0.85" })]);
    await waitFor(() => expect(screen.getByText(/0\.85 · generic/)).toBeTruthy());
  });

  it("distinguishes an empty history from a failed request", async () => {
    await renderWith([]);
    await waitFor(() => expect(screen.getByText(/needs a current crop/i)).toBeTruthy());

    const { getWaterBalance } = await import("@/api/irrigation");
    vi.mocked(getWaterBalance).mockRejectedValue(new Error("boom"));
    render(wrap(<WaterBalanceCard blockId="b2" />));
    await waitFor(() => expect(screen.getByText(/could not load/i)).toBeTruthy());
  });
});

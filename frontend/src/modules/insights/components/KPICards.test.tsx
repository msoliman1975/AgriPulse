import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Alert } from "@/api/alerts";
import { listAlerts } from "@/api/alerts";
import { setupTestI18n } from "@/i18n/testing";

import { KPICards } from "./KPICards";

const FARM_ID = "11111111-1111-1111-1111-111111111111";

function alert(id: string): Alert {
  return {
    id,
    block_id: "b1",
    cell_id: null,
    cell_row: null,
    cell_col: null,
    rule_code: "NDVI_DROP",
    severity: "warning",
    status: "open",
    diagnosis_en: null,
    diagnosis_ar: null,
    prescription_en: null,
    prescription_ar: null,
    prescription_activity_id: null,
    signal_snapshot: null,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-01T00:00:00Z",
    acknowledged_at: null,
    acknowledged_by: null,
    resolved_at: null,
    resolved_by: null,
    snoozed_until: null,
    is_group: false,
    member_count: 0,
    occurrence_count: 1,
    day_streak: 1,
    first_seen_at: null,
    last_seen_at: null,
  };
}

vi.mock("@/api/alerts", async () => {
  const actual = await vi.importActual<typeof import("@/api/alerts")>("@/api/alerts");
  return { ...actual, listAlerts: vi.fn(() => Promise.resolve([])) };
});

vi.mock("@/api/blocks", async () => {
  const actual = await vi.importActual<typeof import("@/api/blocks")>("@/api/blocks");
  return { ...actual, listBlocks: vi.fn(() => Promise.resolve({ items: [], total: 0 })) };
});

// The sparkline is farm-scoped already; stub it so it can't add noise.
vi.mock("@/api/insights", async () => {
  const actual = await vi.importActual<typeof import("@/api/insights")>("@/api/insights");
  return {
    ...actual,
    getFarmAlertTrend: vi.fn(() =>
      Promise.resolve({ farm_id: FARM_ID, days: 7, points: [] as never[] }),
    ),
  };
});

vi.mock("@/queries/irrigation", () => ({
  useIrrigationSchedules: () => ({ data: [], isLoading: false }),
}));
vi.mock("@/queries/plans", () => ({
  useCalendar: () => ({ data: { activities: [] }, isLoading: false }),
}));
vi.mock("@/queries/recommendations", () => ({
  useRecommendations: () => ({ data: [], isLoading: false }),
}));
vi.mock("@/queries/signals", () => ({
  useSignalObservations: () => ({ data: [], isLoading: false }),
}));

const listAlertsMock = vi.mocked(listAlerts);

function renderCards() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <KPICards farmId={FARM_ID} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function alertsTile(): HTMLElement {
  return screen.getByText("Active alerts").closest("button") as HTMLElement;
}

describe("KPICards — active alerts tile", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    listAlertsMock.mockClear();
    listAlertsMock.mockResolvedValue([]);
  });

  // Regression: the tile counted every open alert in the TENANT while its
  // click target (/alerts/:farmId) filters by farm — so a farm with no data
  // of its own showed a non-zero count that linked to an empty page.
  it("asks only for this farm's alerts", async () => {
    renderCards();
    await waitFor(() => expect(listAlertsMock).toHaveBeenCalled());
    for (const [params] of listAlertsMock.mock.calls) {
      expect(params).toMatchObject({ farm_id: FARM_ID, status: "open" });
    }
  });

  // `openAlertCount` is `data.length`, so the page size caps the number the
  // tile can ever show. The API default is 100.
  it("requests past the API's default page size so the count can't plateau", async () => {
    renderCards();
    await waitFor(() => expect(listAlertsMock).toHaveBeenCalled());
    const [params] = listAlertsMock.mock.calls[0];
    expect(params?.limit).toBeGreaterThan(100);
  });

  it("shows zero and the all-clear hint when the farm has no open alerts", async () => {
    renderCards();
    await waitFor(() => expect(listAlertsMock).toHaveBeenCalled());
    await waitFor(() => expect(alertsTile()).toHaveTextContent("0"));
    expect(alertsTile()).toHaveTextContent("All clear");
  });

  it("counts the farm-scoped alerts it got back", async () => {
    listAlertsMock.mockResolvedValue([alert("a1"), alert("a2"), alert("a3")]);
    renderCards();
    await waitFor(() => expect(alertsTile()).toHaveTextContent("3"));
    expect(alertsTile()).toHaveTextContent("needs attention");
  });
});
